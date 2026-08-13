"""Auth header extraction and role checking per PRD section 2.1."""

from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "ResearchOpsAdmin",
    "Researcher",
    "Moderator",
    "Participant",
    "IncentiveOfficer",
    "LegalCounsel",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*allowed):
    """Authenticate and require the role to be one of `allowed`. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_error(ERR_FORBIDDEN, "Role %s is not permitted for this endpoint" % role)
    return user_id, role
