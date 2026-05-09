"""Auth middleware — header / role validation."""
from flask import request

from errors import api_error

VALID_ROLES = {"RightsHolder", "PlatformAdmin"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED if missing."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise api_error("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in VALID_ROLES:
        raise api_error("ERR_UNAUTHENTICATED", f"Unknown role: {role}")
    return user_id, role


def require_roles(allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise api_error("ERR_FORBIDDEN", f"Role {role} is not permitted to perform this operation")
    return user_id, role


def optional_auth():
    """Return (user_id, role) or (None, None) if missing — used for public endpoints."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        return None, None
    return user_id, role
