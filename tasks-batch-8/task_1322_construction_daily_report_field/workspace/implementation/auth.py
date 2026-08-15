from flask import request
from errors import ApiError

ROLES = (
    "SystemAdmin",
    "Superintendent",
    "ProjectManager",
    "SafetyOfficer",
    "ContractorRep",
    "OwnerRep",
)
ALL_ROLES = list(ROLES)


def ctx():
    """Priority 1: header context check. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return uid, role


def need(role, allowed):
    """Priority 2: RBAC check."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
