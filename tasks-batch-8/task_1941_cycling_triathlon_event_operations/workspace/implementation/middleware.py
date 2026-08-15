"""Auth header extraction and role checking per PRD §2.1."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete"}

ALL_ROLES = sorted(ROLES)


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/unrecognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role / X-User-ID headers", 401)
    return user_id, role


def require_roles(*allowed):
    """Check auth + role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, "Role not permitted for this endpoint", 403)
    return user_id, role
