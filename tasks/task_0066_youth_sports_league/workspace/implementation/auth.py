"""Auth header extraction and RBAC."""
from flask import request

from errors import err

ROLES = {"LeagueAdmin", "Coach", "Referee", "ParentGuardian"}


def get_identity():
    """Return (user_id, role) from headers, raising ERR_UNAUTHENTICATED if missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN if role not in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
