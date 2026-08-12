"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "SiteClerk",
    "Driver",
    "Technician",
    "ComplianceOfficer",
    "HostSiteManager",
}


def get_actor():
    """Stage 1: authentication. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(role, allowed):
    """Stage 2 (role permission part). allowed is an iterable of role names."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not permitted for this operation" % role)
