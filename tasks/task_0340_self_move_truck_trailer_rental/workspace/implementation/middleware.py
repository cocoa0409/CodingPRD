"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

ROLES = {"FleetManager", "LocationAgent", "Customer"}


def authenticate():
    """Validate the X-User-ID / X-User-Role headers. Returns (user_id, role).
    Raises ERR_UNAUTHENTICATED on missing/invalid headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE when role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted on this endpoint." % role)
