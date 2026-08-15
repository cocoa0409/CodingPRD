"""Auth middleware — header extraction and role checking."""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLES = {"PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent", "Resident"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED if invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers required")
    if role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"Unrecognized role: {role}")
    return user_id, role


def require_roles(*allowed):
    """Returns (user_id, role) after checking role membership."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_ROLE, f"Role {role} not permitted on this endpoint")
    return user_id, role
