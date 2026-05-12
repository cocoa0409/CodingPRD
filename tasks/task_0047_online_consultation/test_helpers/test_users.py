"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes two role identity shapes:

- Patient, Doctor, Pharmacist are entity-backed -- PRD §2.1: 'When X-User-Role
  is Patient, X-User-ID is the id of the acting Patient; ownership checks on
  any resource that references a Patient compare the resource's patient_id
  field to X-User-ID.' Analogous wording applies to Doctor and Pharmacist.
  Ownership-gated calls (POST /triage-sessions/{id}/assess by patient,
  POST /consultations/{id}/accept by the assigned doctor, POST
  /prescriptions/{id}/approve by a pharmacist that is NOT the drafting doctor)
  MUST use make_<role>_headers(entity_id) with the real entity's id.

- PlatformAdmin is opaque -- PRD §2.1: 'X-User-ID is an opaque operator
  identifier not tied to any persisted entity. The server may record it ...
  but does not compare it to any entity's id.' The shared TEST_USERS
  constant is canonical for this role.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared fallback constants. Canonical for PlatformAdmin (opaque); fallback
# for the entity-backed roles on tests that do NOT exercise ownership
# (e.g., RBAC ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_AUTH_MISSING).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role -- canonical constant.
    "platform_admin_headers": build_user_headers(
        "admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "admin-002", "PlatformAdmin",
    ),

    # Fallback constants for entity-backed roles. Use ONLY when ownership
    # is not exercised.
    "patient_headers": build_user_headers(
        "patient-fallback", "Patient",
    ),
    "doctor_headers": build_user_headers(
        "doctor-fallback", "Doctor",
    ),
    "pharmacist_headers": build_user_headers(
        "pharmacist-fallback", "Pharmacist",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity-backed roles. Use these whenever the
# call is ownership-gated so the X-User-ID resolves to a real entity id.
# ---------------------------------------------------------------------------
def make_patient_headers(patient_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Patient, X-User-ID is the id of the
    acting Patient; ownership checks ... compare the resource's patient_id
    field to X-User-ID.' Pass the actual Patient.id minted by POST
    /consultation/patients."""
    return build_user_headers(patient_id, "Patient")


def make_doctor_headers(doctor_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Doctor, X-User-ID is the id of the
    acting Doctor; ownership checks on a Consultation compare its doctor_id
    to X-User-ID, and ownership of a Prescription is via
    drafting_doctor_id.' Pass the actual Doctor.id minted by POST
    /consultation/doctors."""
    return build_user_headers(doctor_id, "Doctor")


def make_pharmacist_headers(pharmacist_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Pharmacist, X-User-ID is the id of
    the acting Pharmacist; the server records it on
    Prescription.reviewing_pharmacist_id when the pharmacist approves or
    rejects, and uses it for the segregation-of-duties check against
    drafting_doctor_id.' Pass the actual Pharmacist.id minted by POST
    /consultation/pharmacists."""
    return build_user_headers(pharmacist_id, "Pharmacist")


def make_platform_admin_headers(
    admin_id: str = "admin-001",
) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is an opaque operator id."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_patient_headers",
    "make_doctor_headers",
    "make_pharmacist_headers",
    "make_platform_admin_headers",
]
