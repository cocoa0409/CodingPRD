"""Auth helpers: extract headers, role validation, identity matching."""
from flask import request
from common import ApiError


VALID_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role) or raise ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_AUTH_REQUIRED", 401, "Missing auth headers")
    if role not in VALID_ROLES:
        raise ApiError("ERR_AUTH_REQUIRED", 401, "Invalid role")
    return user_id, role


def require_role(allowed_roles):
    """Raise ERR_FORBIDDEN if role not in allowed_roles. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, f"Role {role} not permitted")
    return user_id, role
