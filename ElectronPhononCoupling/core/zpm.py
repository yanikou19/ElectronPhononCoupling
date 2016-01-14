from __future__ import print_function

import sys
import os
import warnings

import numpy as N
from numpy import zeros

from .constants import tol6, tol8, Ha2eV, kb_HaK

from .dynmat import compute_dynmat, get_reduced_displ
from .degenerate import make_average, symmetrize_fan_degen

from .mathutil import delta_lorentzian
from .rf_mods import RFStructure 


# =========================================================================== #

def get_qpt_zpr_static(args, ddw, degen):
    """Compute the zpr contribution from one q-point in a static scheme."""

    iqpt, wtq, eigq_fname, DDB_fname, EIGR2D_fname = args

    eigq = RFStructure(eigq_fname)
    DDB = RFStructure(DDB_fname)
    EIGR2D = RFStructure(EIGR2D_fname)

    qpt_corr = zeros((3, EIGR2D.nkpt, EIGR2D.nband), dtype=complex)

    # Current Q-point calculated
    print("Q-point: {} with wtq = {} and reduced coord. {}".format(iqpt,wtq,EIGR2D.iqpt))

    # Find phonon freq and eigendisplacement from _DDB
    omega, eigvect, gprimd = compute_dynmat(DDB)

    # Get reduced displacement (scaled with frequency)
    displ_red_FAN2, displ_red_DDW2 = get_reduced_displ(EIGR2D.natom, eigvect, omega, gprimd)

    # Sum over (idir, iat, jdir, jat) to obtain (nmode, nkpt, nband)
    fan_corrQ = N.einsum('ijklmn,olnkm->oij', EIGR2D.EIG2D, displ_red_FAN2)
    ddw_corrQ = N.einsum('ijklmn,olnkm->oij', ddw, displ_red_DDW2)  

    # Sum all modes
    fan_corr = N.sum(fan_corrQ, axis=0)
    ddw_corr = N.sum(ddw_corrQ, axis=0)

    eigen_corr = (fan_corr[:,:] - ddw_corr[:,:])
    qpt_corr[0,:,:] = eigen_corr[:,:] * wtq
    qpt_corr[1,:,:] = fan_corr[:,:] * wtq
    qpt_corr[2,:,:] = ddw_corr[:,:] * wtq

    qpt_corr = make_average(qpt_corr, degen)

    return qpt_corr


def get_qpt_zpr_dynamical(args, ddw, ddw_active, option, smearing, eig0, degen):
    """Compute the zpr contribution from one q-point in a dynamical scheme."""

    iqpt, wtq, eigq_files, DDB_files, EIGR2D_files, FAN_files = args
  
    FANterm = RFStructure(FAN_files)
    FAN = FANterm.FAN
    DDB = RFStructure(DDB_files)
    EIGR2D = RFStructure(EIGR2D_files)
    eigq = RFStructure(eigq_files)
  
    nkpt = EIGR2D.nkpt
    nband = EIGR2D.nband
    natom = EIGR2D.natom
  
    qpt_corr = zeros((3,nkpt,nband), dtype=complex)
  
    # Current Q-point calculated
    print("Q-point: {} with wtq = {} and reduced coord. {}".format(iqpt, wtq, EIGR2D.iqpt))
  
    # Find phonon freq and eigendisplacement from _DDB
    omega, eigvect, gprimd = compute_dynmat(DDB)
  
    fan_corr = zeros((nkpt,nband), dtype=complex)
    ddw_corr = zeros((nkpt,nband), dtype=complex)
    fan_add  = zeros((nkpt,nband), dtype=complex)
    ddw_add  = zeros((nkpt,nband), dtype=complex)
  
    # Get reduced displacement (scaled with frequency)
    displ_red_FAN2, displ_red_DDW2 = get_reduced_displ(natom, eigvect, omega, gprimd)
  
    # fan_corrQ and ddw_corrQ contains the ZPR on Sternheimer space.
    fan_corrQ = N.einsum('ijklmn,olnkm->oij', EIGR2D.EIG2D, displ_red_FAN2)
    ddw_corrQ = N.einsum('ijklmn,olnkm->oij', ddw, displ_red_DDW2)
  
    fan_corr = N.sum(fan_corrQ,axis=0)
    ddw_corr = N.sum(ddw_corrQ,axis=0)
  
    # Now compute active space
    #print("Now compute active space ...")
  
    # nkpt, nband, nband, nmode
    fan_addQ = N.einsum('ijklmno,plnkm->ijop', FAN, displ_red_FAN2) 
    ddw_addQ = N.einsum('ijklmno,plnkm->ijop', ddw_active, displ_red_DDW2) 

    # Enforce the diagonal coupling terms to be zero at Gamma
    ddw_addQ = symmetrize_fan_degen(ddw_addQ, degen)
    if iqpt == 0:
        fan_addQ = symmetrize_fan_degen(fan_addQ, degen)
  
    if option == 'static':

        # nkpt, nband, nband
        fan_tmp = N.sum(fan_addQ, axis=3)
        ddw_tmp = N.sum(ddw_addQ, axis=3)
  
        # nkpt, nband, nband
        delta_E = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
                 - N.einsum('ij,k->ikj', eigq.EIG[0,:,:].real, N.ones(nband)))

        # nkpt, nband, nband
        delta_E_ddw = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
                     - N.einsum('ij,k->ikj', eig0[0,:,:].real, N.ones(nband)))

        # nkpt, nband, nband
        div =  delta_E / (delta_E ** 2 + smearing ** 2)

        # nkpt, nband
        fan_add = N.einsum('ijk,ijk->ij', fan_tmp, div)

        # nkpt, nband, nband
        div_ddw = delta_E_ddw / (delta_E_ddw ** 2 + smearing ** 2)

        # nkpt, nband
        ddw_add = N.einsum('ijk,ijk->ij', ddw_tmp, div_ddw)

    elif option == 'dynamical':

        # nkpt, nband, nband
        ddw_tmp = N.sum(ddw_addQ, axis=3)

        # nband
        occtmp = EIGR2D.occ[0,0,:]/2

        # nkpt, nband, nband
        delta_E = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
                 - N.einsum('ij,k->ikj', eigq.EIG[0,:,:].real, N.ones(nband))
                 - N.einsum('ij,k->ijk', N.ones((nkpt,nband)), (2*occtmp-1)) * smearing * 1j)

        # nkpt, nband, nband
        delta_E_ddw = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
                     - N.einsum('ij,k->ikj', eig0[0,:,:].real, N.ones(nband))
                     - N.einsum('ij,k->ijk', N.ones((nkpt,nband)), (2*occtmp-1)) * smearing * 1j)

        # nkpt, nband
        ddw_add = N.einsum('ijk,ijk->ij', ddw_tmp, 1.0 / delta_E_ddw)

        # nmode
        omegatmp = omega[:].real

        # nband
        num1 = 1.0 - occtmp

        # nkpt, nband, nband, nmode
        deno1 = (N.einsum('ijk,l->ijkl', delta_E, N.ones(3*natom))
               - N.einsum('ijk,l->ijkl', N.ones((nkpt,nband,nband)), omegatmp))

        # nmode, nband, nkpt, nband
        div1 = N.einsum('i,jkil->lijk', num1, 1.0 / deno1)

        # nkpt, nband, nband, nmode
        deno2 = (N.einsum('ijk,l->ijkl', delta_E, N.ones(3*natom))
               + N.einsum('ijk,l->ijkl', N.ones((nkpt,nband,nband)), omegatmp))

        # nmode, nband, nkpt, nband
        div2 = N.einsum('i,jkil->lijk', occtmp, 1.0 / deno2)

        # nkpt, nband
        fan_add = N.einsum('ijkl,lkij->ij', fan_addQ, div1 + div2)

    else:

        raise ValueError("option must be either 'static' or 'dynamical'.")
  
    # Correction from active space 
    fan_corr += fan_add
    ddw_corr += ddw_add
    eigen_corr = fan_corr[:,:] - ddw_corr[:,:]

    qpt_corr[0,:,:] = eigen_corr[:,:] * wtq
    qpt_corr[1,:,:] = fan_corr[:,:] * wtq
    qpt_corr[2,:,:] = ddw_corr[:,:] * wtq

    qpt_corr = make_average(qpt_corr, degen)
  
    return qpt_corr


def get_qpt_zpb_dynamical(args, smearing, eig0, degen):
    """
    Compute the zp broadening contribution from one q-point in a dynamical scheme.
    Only take the active space contribution.
    """

    iqpt, wtq, eigq_files, DDB_files, FAN_files = args
  
    FANterm = RFStructure(FAN_files)
    FAN = FANterm.FAN
    DDB = RFStructure(DDB_files)
    eigq = RFStructure(eigq_files)

    nkpt = FANterm.nkpt
    nband = FANterm.nband
    natom = FANterm.natom
  
    # nband
    occ = FANterm.occ[0,0,:] / 2  # FIXME does not take spin into account

    qpt_brd = zeros((nkpt, nband),dtype=complex)
  
    # Current Q-point calculated
    print("Q-point: {} with wtq = {} and reduced coord. {}".format(iqpt, wtq, DDB.iqpt))
  
    # Find phonon freq and eigendisplacement from _DDB
    omega, eigvect, gprimd = compute_dynmat(DDB)
  
    # nmode
    omega = omega[:].real

    fan_add  = zeros((nkpt,nband), dtype=complex)
  
    # Get reduced displacement (scaled with frequency)
    displ_red_FAN2, displ_red_DDW2 = get_reduced_displ(natom, eigvect, omega, gprimd)
  
    # nkpt, nband, nband, nmode
    fan_addQ = N.einsum('ijklmno,plnkm->ijop', FAN, displ_red_FAN2) 

    # Enforce the diagonal coupling terms to be zero at Gamma
    if iqpt == 0:
        fan_addQ = symmetrize_fan_degen(fan_addQ, degen)
  
    # nkpt, nband, nband
    delta_E = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
             - N.einsum('ij,k->ikj', eigq.EIG[0,:,:].real, N.ones(nband)))

    # nband
    num1 = - (1. - occ) * (2 * occ - 1.)
    num2 = - occ * (2 * occ - 1.)

    # nkpt, nband, nband, nmode
    deno1 = (N.einsum('ijk,l->ijkl', delta_E, N.ones(3*natom))
            - N.einsum('ijk,l->ijkl', N.ones((nkpt,nband,nband)), omega))
    delta1 =  N.pi * delta_lorentzian(deno1, smearing)

    # nkpt, nband, nband, nmode
    deno2 = (N.einsum('ijk,l->ijkl', delta_E, N.ones(3*natom))
            + N.einsum('ijk,l->ijkl', N.ones((nkpt,nband,nband)), omega))
    delta2 = N.pi * delta_lorentzian(deno2, smearing)

    term1 = N.einsum('i,jkil->lijk', num1, delta1)
    term2 = N.einsum('i,jkil->lijk', num2, delta2)

    deltas = term1 + term2

    # nkpt, nband
    fan_add = N.einsum('ijkl,lkij->ij', fan_addQ, deltas)
  
    # Correction from active space 
    qpt_brd = fan_add[:,:] * wtq

    qpt_brd = make_average(qpt_brd, degen)
  
    return qpt_brd


def get_qpt_zpb_static_control(args, smearing, eig0, degen):
    """
    Compute the zp broadening contribution from one q-point in a static scheme.
    Only take the active space contribution.
    """

    iqpt, wtq, eigq_files, DDB_files, FAN_files = args
  
    FANterm = RFStructure(FAN_files)
    FAN = FANterm.FAN
    DDB = RFStructure(DDB_files)
    eigq = RFStructure(eigq_files)

    nkpt = FANterm.nkpt
    nband = FANterm.nband
    natom = FANterm.natom
  
    # nband
    occ = FANterm.occ[0,0,:] / 2  # FIXME does not take spin into account

    qpt_brd = zeros((nkpt, nband),dtype=complex)
  
    # Current Q-point calculated
    print("Q-point: {} with wtq = {} and reduced coord. {}".format(iqpt, wtq, DDB.iqpt))
  
    # Find phonon freq and eigendisplacement from _DDB
    omega, eigvect, gprimd = compute_dynmat(DDB)
  
    # nmode
    omega = omega[:].real

    fan_add  = zeros((nkpt,nband), dtype=complex)
  
    # Get reduced displacement (scaled with frequency)
    displ_red_FAN2, displ_red_DDW2 = get_reduced_displ(natom, eigvect, omega, gprimd)
  
    # nkpt, nband, nband, nmode
    fan_addQ = N.einsum('ijklmno,plnkm->ijop', FAN, displ_red_FAN2) 
  
    # Enforce the diagonal coupling terms to be zero at Gamma
    if iqpt == 0:
        fan_addQ = symmetrize_fan_degen(fan_addQ, degen)
  
    # nkpt, nband, nband
    delta_E = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
             - N.einsum('ij,k->ikj', eigq.EIG[0,:,:].real, N.ones(nband)))

    # nband
    num = - (2 * occ - 1.)

    # nkpt, nband, nband, nmode
    delta =  N.pi * delta_lorentzian(delta_E, smearing)

    # nband, nkpt, nband
    deltasign = N.einsum('i,jki->ijk', num, delta)

    # nkpt, nband
    fan_add = N.einsum('ijkl,kij->ij', fan_addQ, deltasign)
  
    # Correction from active space 
    qpt_brd = fan_add[:,:] * wtq

    qpt_brd = make_average(qpt_brd, degen)
  
    return qpt_brd


def get_qpt_zp_self_energy(args, ddw, ddw_active, smearing, eig0, degen, omegase):
    """
    Compute the zp frequency-dependent dynamical self-energy from one q-point.

    The self-energy is evaluated on a frequency mesh 'omegase' that is shifted by the bare energies,
    such that, what is retured is

        Simga'_kn(omega) = Sigma_kn(omega + E^0_kn)

    """

    iqpt, wtq, eigq_files, DDB_files, EIGR2D_files, FAN_files = args
  
    FANterm = RFStructure(FAN_files)
    FAN = FANterm.FAN
    DDB = RFStructure(DDB_files)
    EIGR2D = RFStructure(EIGR2D_files)
    eigq = RFStructure(eigq_files)
  
    nkpt = EIGR2D.nkpt
    nband = EIGR2D.nband
    natom = EIGR2D.natom

    nomegase = len(omegase)
  
    qpt_sigma = zeros((nkpt,nband,nomegase), dtype=complex)
  
    # Current Q-point calculated
    print("Q-point: {} with wtq = {} and reduced coord. {}".format(iqpt, wtq, EIGR2D.iqpt))
  
    # Find phonon freq and eigendisplacement from _DDB
    omega, eigvect, gprimd = compute_dynmat(DDB)
  
    fan_corr = zeros((nomegase,nkpt,nband), dtype=complex)
    ddw_corr = zeros((nkpt,nband), dtype=complex)
    fan_add  = zeros((nomegase,nkpt,nband), dtype=complex)
    ddw_add  = zeros((nkpt,nband), dtype=complex)
  
    # Get reduced displacement (scaled with frequency)
    displ_red_FAN2, displ_red_DDW2 = get_reduced_displ(natom, eigvect, omega, gprimd)
  
    # fan_corrQ and ddw_corrQ contains the ZPR on Sternheimer space.
    fan_corrQ = N.einsum('ijklmn,olnkm->oij', EIGR2D.EIG2D, displ_red_FAN2)
    fan_corrQ = N.einsum('oij,m->omij', fan_corrQ, N.ones(nomegase))
    ddw_corrQ = N.einsum('ijklmn,olnkm->oij', ddw, displ_red_DDW2)
  
    # Sum Sternheimer (upper) contribution
    fan_corr = N.sum(fan_corrQ,axis=0)
    ddw_corr = N.sum(ddw_corrQ,axis=0)
  
    # Now compute active space
    #print("Now compute active space ...")
  
    # nkpt, nband, nband, nmode
    fan_addQ = N.einsum('ijklmno,plnkm->ijop', FAN, displ_red_FAN2) 
    ddw_addQ = N.einsum('ijklmno,plnkm->ijop', ddw_active, displ_red_DDW2) 

    # Enforce the diagonal coupling terms to be zero at Gamma
    ddw_addQ = symmetrize_fan_degen(ddw_addQ, degen)
    if iqpt == 0:
        fan_addQ = symmetrize_fan_degen(fan_addQ, degen)
  

    # nkpt, nband, nband
    ddw_tmp = N.sum(ddw_addQ, axis=3)

    # nband
    occtmp = EIGR2D.occ[0,0,:]/2

    # nkpt, nband, nband
    delta_E_ddw = (N.einsum('ij,k->ijk', eig0[0,:,:].real, N.ones(nband))
                 - N.einsum('ij,k->ikj', eig0[0,:,:].real, N.ones(nband))
                 - N.einsum('ij,k->ijk', N.ones((nkpt,nband)), (2*occtmp-1)) * smearing * 1j)

    # nkpt, nband
    ddw_add = N.einsum('ijk,ijk->ij', ddw_tmp, 1.0 / delta_E_ddw)

    # nmode
    omegatmp = omega[:].real

    # nband
    num1 = 1.0 - occtmp

    # nomegase, nkpt, nband
    fan_add = zeros((nomegase, nkpt, nband), dtype=complex)

    for kband in range(nband):

        # nkpt, nband
        # delta_E[ikpt,jband] = E[ikpt,jband] - E[ikpt,kband] - (2f[kband] -1) * eta * 1j
        delta_E = (eig0[0,:,:].real
                 - N.einsum('i,j->ij', eigq.EIG[0,:,kband].real, N.ones(nband))
                 - N.ones((nkpt,nband)) * (2*occtmp[kband]-1) * smearing * 1j)

        # nkpt, nband, nomegase
        # delta_E_omega[ikpt,jband,lomega] = omega[lomega] + E[ikpt,jband] - E[ikpt,kband] - (2f[kband] -1) * eta * 1j
        delta_E_omega = (N.einsum('ij,l->ijl', delta_E, N.ones(nomegase))
                       + N.einsum('ij,l->ijl', N.ones((nkpt,nband)), omegase))

        # nkpt, nband, nomegase, nmode
        deno1 = (N.einsum('ijl,m->ijlm', delta_E_omega, N.ones(3*natom))
               - N.einsum('ijl,m->ijlm', N.ones((nkpt,nband,nomegase)), omegatmp))

        # nmode, nkpt, nband, nomegase
        div1 = num1[kband] * N.einsum('ijlm->mijl', 1.0 / deno1)

        del deno1

        # nkpt, nband, nomegase, nmode
        deno2 = (N.einsum('ijl,m->ijlm', delta_E_omega, N.ones(3*natom))
               + N.einsum('ijl,m->ijlm', N.ones((nkpt,nband,nomegase)), omegatmp))

        del delta_E_omega

        # nmode, nkpt, nband, nomegase
        div2 = occtmp[kband] * N.einsum('ijlm->mijl', 1.0 / deno2)

        del deno2

        # nomegase, nkpt, nband
        fan_add += N.einsum('ijm,mijl->lij', fan_addQ[:,:,kband,:], div1 + div2)

        del div1, div2
  

    # Correction from active space 
    fan_corr += fan_add
    ddw_corr += ddw_add
    ddw_corr = N.einsum('ij,m->mij', ddw_corr, N.ones(nomegase))

    qpt_sigma = (fan_corr[:,:,:] - ddw_corr[:,:,:]) * wtq

    qpt_sigma = make_average(qpt_sigma, degen)
    qpt_sigma = N.einsum('mij->ijm', qpt_sigma)
  
    return qpt_sigma

