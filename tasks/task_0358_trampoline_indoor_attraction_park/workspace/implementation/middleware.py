"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"ParkManager", "FrontDesk", "Member", "Guardian"}


def get_identity():
    """Return (user_id, user_role) from the request headers."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def authenticate():
    """Validate the two mandatory auth headers.

    Both X-User-ID and X-User-Role must be present and the role must be a
    recognized role, else ERR_UNAUTHENTICATED (PRD §2.1 / validation priority 1).
    Returns (user_id, user_role).
    """
    user_id, user_role = get_identity()
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, user_role


def require_role(user_role, allowed):
    """Enforce that the acting role is permitted (priority 2 -> ERR_FORBIDDEN_ROLE)."""
    if user_role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
