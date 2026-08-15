"""Auth header extraction and role checking (PRD section 2.1)."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "AccountManager",
    "ProjectManager",
    "FieldSupervisor",
    "SafetyManager",
    "ComplianceOfficer",
    "EnvironmentalApprover",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    """Priority 1: X-User-Role names a declared role and X-User-ID is present."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-Role header is missing or does not name a declared role")
    if user_id is None or user_id == "":
        raise ApiError(ERR_UNAUTHENTICATED, 401, "X-User-ID header is missing")
    return user_id, role


def require_roles(roles):
    """Priority 1 then 2: authenticate, then check endpoint role membership."""
    user_id, role = authenticate()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role %s is not authorized for this endpoint" % role)
    return user_id, role
