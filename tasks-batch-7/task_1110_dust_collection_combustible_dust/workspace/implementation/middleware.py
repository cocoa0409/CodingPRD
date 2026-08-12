"""Auth header extraction and role checking per PRD §2.1 and SCAFFOLD §1.4."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "PlatformAdmin",
    "ComplianceManager",
    "ComplianceEngineer",
    "SafetyManager",
    "HotWorkPerformer",
    "HousekeepingAuditor",
    "InspectorUser",
    "IncidentInvestigator",
}


def get_auth():
    """Validate X-User-Role and X-User-ID headers.

    Returns (user_id, role). Raises ApiError on failure.
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role header", 401)
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID header", 401)
    return user_id, role


def require_roles(*allowed):
    """Validate auth then enforce that the role is in the allowed set.

    Returns (user_id, role).
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, "Role not permitted for this endpoint", 403)
    return user_id, role
