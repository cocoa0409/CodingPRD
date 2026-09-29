"""Role headers for the pulmonary function laboratory API.

Two roles are opaque: ``LabManager`` and ``ComplianceAuditor`` are recognised by
their role header alone, so a fixed identifier is enough for them.

The other three roles are backed by a ``Staff`` row and the API compares the
``X-User-ID`` against that row's ``role_type``, so their headers must always be
built from the identifier of a staff member the test actually registered.  Use
the ``make_*_headers`` builders for those; never a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

ROLE_LAB_MANAGER = "LabManager"
ROLE_TECHNOLOGIST = "Technologist"
ROLE_ORDERING_PHYSICIAN = "OrderingPhysician"
ROLE_INTERPRETING_PHYSICIAN = "InterpretingPhysician"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = (
    ROLE_LAB_MANAGER,
    ROLE_TECHNOLOGIST,
    ROLE_ORDERING_PHYSICIAN,
    ROLE_INTERPRETING_PHYSICIAN,
    ROLE_COMPLIANCE_AUDITOR,
)

# Opaque identities — no Staff row backs them.
LAB_MANAGER_USER_ID = "9f2c1a30-0000-4000-8000-00000000aa01"
COMPLIANCE_AUDITOR_USER_ID = "9f2c1a30-0000-4000-8000-00000000aa02"

LAB_MANAGER = build_user_headers(LAB_MANAGER_USER_ID, ROLE_LAB_MANAGER)
COMPLIANCE_AUDITOR = build_user_headers(
    COMPLIANCE_AUDITOR_USER_ID, ROLE_COMPLIANCE_AUDITOR
)

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_LAB_MANAGER: LAB_MANAGER,
    ROLE_COMPLIANCE_AUDITOR: COMPLIANCE_AUDITOR,
}


def make_technologist_headers(staff_id: str) -> Dict[str, str]:
    """Headers for the Technologist whose Staff row has this identifier."""
    return build_user_headers(staff_id, ROLE_TECHNOLOGIST)


def make_ordering_physician_headers(staff_id: str) -> Dict[str, str]:
    """Headers for the OrderingPhysician whose Staff row has this identifier."""
    return build_user_headers(staff_id, ROLE_ORDERING_PHYSICIAN)


def make_interpreting_physician_headers(staff_id: str) -> Dict[str, str]:
    """Headers for the InterpretingPhysician whose Staff row has this identifier."""
    return build_user_headers(staff_id, ROLE_INTERPRETING_PHYSICIAN)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/identifier pair, declared or otherwise."""
    return build_user_headers(user_id, role)
