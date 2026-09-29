"""Header builders for the five authenticated roles (PRD 2.1).

``ComplianceOfficer`` is an opaque operator identity: its ``X-User-ID`` "is an
opaque operator identifier not tied to any persisted entity", so a fixed literal
is enough. The other four roles are backed by a ``Clinician`` row, so their
builders take the clinician id the caller just created — that id is what the
server stamps into ``initiated_by_clinician_id`` and friends, and what the
segregation-of-duties rules compare.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

#: Opaque operator identifier for the compliance office.
COMPLIANCE_OFFICER_USER_ID = "ops-compliance-officer-2367"

#: A second opaque operator, for tests that need two distinct officers.
ALTERNATE_COMPLIANCE_OFFICER_USER_ID = "ops-compliance-officer-2367-b"


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> Dict[str, str]:
    """Headers for the compliance office (PRD 2.1)."""
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER.value)


def make_intake_clinician_headers(user_id: str) -> Dict[str, str]:
    """Headers for an intake clinician, identified by their clinician id."""
    return build_user_headers(user_id, Role.INTAKE_CLINICIAN.value)


def make_attending_psychiatrist_headers(user_id: str) -> Dict[str, str]:
    """Headers for an attending psychiatrist, identified by clinician id."""
    return build_user_headers(user_id, Role.ATTENDING_PSYCHIATRIST.value)


def make_charge_nurse_headers(user_id: str) -> Dict[str, str]:
    """Headers for a charge nurse, identified by clinician id."""
    return build_user_headers(user_id, Role.CHARGE_NURSE.value)


def make_patient_rights_advocate_headers(user_id: str) -> Dict[str, str]:
    """Headers for a patient rights advocate, identified by clinician id."""
    return build_user_headers(user_id, Role.PATIENT_RIGHTS_ADVOCATE.value)


def make_headers(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary role, defaulting the opaque operator id."""
    if user_id is None:
        user_id = COMPLIANCE_OFFICER_USER_ID
    return build_user_headers(user_id, role)


def make_unauthenticated_headers(
    role: Optional[str] = None, user_id: Optional[str] = None
) -> Dict[str, str]:
    """Headers deliberately missing one of the two identity headers.

    With neither argument the result carries no identity at all; supplying only
    ``role`` omits ``X-User-ID``, and supplying only ``user_id`` omits
    ``X-User-Role``.
    """
    headers = {"Content-Type": "application/json"}
    if role is not None:
        headers["X-User-Role"] = role
    if user_id is not None:
        headers["X-User-ID"] = user_id
    return headers


#: Pre-built headers for the opaque compliance operator.
COMPLIANCE_OFFICER_HEADERS = make_compliance_officer_headers()

#: The four clinician-backed roles, for exhaustive role sweeps.
CLINICIAN_BACKED_ROLES = (
    Role.INTAKE_CLINICIAN.value,
    Role.ATTENDING_PSYCHIATRIST.value,
    Role.CHARGE_NURSE.value,
    Role.PATIENT_RIGHTS_ADVOCATE.value,
)

#: All five accepted header roles.
ALL_ROLES = (Role.COMPLIANCE_OFFICER.value,) + CLINICIAN_BACKED_ROLES

#: Role strings outside the accepted five (PRD 2.1 treats these as unauthenticated).
UNKNOWN_ROLES = ("Nurse", "Administrator", "attendingpsychiatrist", "")
