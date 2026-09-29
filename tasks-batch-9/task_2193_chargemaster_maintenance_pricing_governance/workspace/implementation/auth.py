"""Authentication (rank 1), endpoint role admission (rank 2) and
DepartmentManager scope (rank 3).  PRD 2.1 / 2.9.
"""

from flask import request

from errors import fail
from store import STORE

ROLES = (
    "SystemAdmin",
    "RevenueIntegrityAnalyst",
    "PricingCommitteeApprover",
    "ComplianceOfficer",
    "ContractManager",
    "DepartmentManager",
)

ALL_ROLES = list(ROLES)

SA = "SystemAdmin"
RIA = "RevenueIntegrityAnalyst"
PCA = "PricingCommitteeApprover"
CO = "ComplianceOfficer"
CM = "ContractManager"
DM = "DepartmentManager"


def actor():
    """Rank 1 — headers present and role legal."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require(*allowed):
    """Ranks 1 and 2 together; returns (user_id, role)."""
    user_id, role = actor()
    allowed_roles = []
    for entry in allowed:
        if isinstance(entry, (list, tuple)):
            allowed_roles.extend(entry)
        else:
            allowed_roles.append(entry)
    if role not in allowed_roles:
        fail(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not call this endpoint." % role,
        )
    return user_id, role


def scope_check(user_id, role, department_id):
    """Rank 3 — DepartmentManager acts only for its own department.

    A department_id that does not resolve is left to the existence ranks.
    """
    if role != DM:
        return
    if department_id is None:
        return
    dept = STORE.departments.get(department_id)
    if dept is None:
        return
    if dept.get("manager_user_id") != user_id:
        fail(
            "ERR_DEPARTMENT_SCOPE_VIOLATION",
            "User is not the manager of department %s." % department_id,
        )


def scope_owner_check(user_id, role, owner_user_id):
    """Rank 3 — narrower ownership rule for withdraw / resubmit."""
    if role != DM:
        return
    if owner_user_id is not None and owner_user_id != user_id:
        fail(
            "ERR_DEPARTMENT_SCOPE_VIOLATION",
            "Only the original submitter may perform this action.",
        )
