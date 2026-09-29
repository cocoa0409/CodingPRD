"""Authentication and RBAC (PRD 2.1, validation priorities 1 and 2)."""

from flask import request

from errors import ApiError

ROLES = ("StaffingOfficer", "CompanyOfficer", "Firefighter", "PayrollAnalyst")
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    """Priority 1 then priority 2.  Runs before path resolution."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or invalid.")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorized for this operation." % role,
        )
    return str(user_id), role
