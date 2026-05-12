"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- Nurse: entity_backed:Nurse. PRD §2.1: 'When X-User-Role is Nurse, the
  value of X-User-ID is the id of the acting Nurse row; ownership checks
  on any resource that references a nurse -- most importantly
  Dispatch.nurse_id, ServiceRecord.nurse_id, and the assigned-nurse view
  of Order -- compare the resource's foreign-key field directly to
  X-User-ID.' Ownership-gated calls (POST /dispatches/{id}/accept,
  POST /dispatches/{id}/reject, POST /orders/{id}/service-record, and
  related Nurse-only mutations) MUST use make_nurse_headers(nurse_id)
  with the actual Nurse.id.

- Patient: opaque per PRD §2.1, but the patient_id stored on Order /
  Package / Complaint is compared to X-User-ID for own-resource reads
  and for Patient ownership-gated mutations like cancel and
  confirm-completion. Tests that exercise ownership MUST therefore use
  make_patient_headers(patient_id) threading the same X-User-ID used at
  Order/Package/Complaint creation time.

- ComplianceOfficer / PlatformAdmin: opaque per PRD §2.1. The shared
  TEST_USERS constants are canonical for these roles.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For the two opaque operator roles, these are
# canonical. For Nurse and Patient (whose identities flow through to
# stored fields the platform compares against), the constants here are
# fallbacks for tests that do NOT exercise ownership comparison
# (e.g., role-authorization 403 tests, schema-violation tests).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator roles -- canonical shared constants.
    "compliance_officer_headers": build_user_headers(
        "compliance-001", "ComplianceOfficer"
    ),
    "compliance_officer_headers_alt": build_user_headers(
        "compliance-002", "ComplianceOfficer"
    ),
    "platform_admin_headers": build_user_headers(
        "admin-001", "PlatformAdmin"
    ),
    "platform_admin_headers_alt": build_user_headers(
        "admin-002", "PlatformAdmin"
    ),

    # Fallback constants for identity-bearing roles. Use only when the
    # call under test does NOT exercise an ownership comparison
    # (e.g., 403 wrong-role tests, 404 missing-resource tests).
    "nurse_headers": build_user_headers(
        "nurse-fallback", "Nurse"
    ),
    "patient_headers": build_user_headers(
        "patient-fallback", "Patient"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders for identity-bearing roles (PRD §2.1).
# Use these whenever the call is ownership-gated.
# ---------------------------------------------------------------------------
def make_nurse_headers(nurse_id: str) -> Dict[str, str]:
    """Nurse headers (entity_backed:Nurse).

    Pass the Nurse.id of the acting nurse. PRD §2.1: 'ownership checks on
    any resource that references a nurse -- most importantly
    Dispatch.nurse_id, ServiceRecord.nurse_id, and the assigned-nurse
    view of Order -- compare the resource's foreign-key field directly
    to X-User-ID.'
    """
    return build_user_headers(nurse_id, "Nurse")


def make_patient_headers(patient_id: str) -> Dict[str, str]:
    """Patient headers (opaque, but threaded through stored patient_id).

    PRD §2.1: 'the server stores it on Order.patient_id at order creation,
    on Package.patient_id at package creation, and on Complaint.patient_id
    (copied through from the subject order). Subsequent ownership checks
    for patient-scoped reads compare these stored patient_id values
    against the caller's X-User-ID.'

    Pass the same patient_id used when creating the Order or Package so
    cancel / confirm-completion / get-own-order calls succeed.
    """
    return build_user_headers(patient_id, "Patient")


def make_compliance_officer_headers(
    officer_id: str = "compliance-001",
) -> Dict[str, str]:
    return build_user_headers(officer_id, "ComplianceOfficer")


def make_platform_admin_headers(
    admin_id: str = "admin-001",
) -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_nurse_headers",
    "make_patient_headers",
    "make_compliance_officer_headers",
    "make_platform_admin_headers",
]
