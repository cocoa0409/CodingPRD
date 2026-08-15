"""Auth context extraction and role checking (validation priorities 1, 2, 6)."""

from flask import request, g

from errors import (
    ERR_MISSING_USER_CONTEXT,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_RESOURCE_OWNER,
    raise_err,
)

ROLES = (
    "CarrierRep",
    "Dispatcher",
    "EscortOperator",
    "RouteSurveyor",
    "SafetyManager",
    "BillingClerk",
    "FinanceManager",
)

ALL_ROLES = ROLES


def require_roles(*allowed):
    """Priorities 1-2: headers present + declared role; role authorized for endpoint."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_USER_CONTEXT,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, f"Role {role} is not authorized for this endpoint")
    g.user_id = uid
    g.user_role = role
    return uid, role


def check_carrier_owner(job):
    """Priority 6: CarrierRep caller must own the job's carrier."""
    if g.user_role == "CarrierRep" and job["carrier_id"] != g.user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "CarrierRep does not own this job's carrier")


def check_assignment_owner(assignment):
    """Priority 6: EscortOperator caller must be the assigned escort."""
    if g.user_role == "EscortOperator" and assignment["escort_id"] != g.user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "EscortOperator is not the assigned escort")
