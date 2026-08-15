"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.7)."""

from flask import request

from errors import err_unauthenticated, err_forbidden


ROLES = {
    "Anonymous",
    "Contestant",
    "ContestLead",
    "Judge",
    "SafetyOfficer",
    "StageManager",
    "Treasurer",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Authenticate then authorize; returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_forbidden()
    return user_id, role
