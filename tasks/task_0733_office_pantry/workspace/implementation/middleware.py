"""Auth header extraction and role checking."""
from flask import request

from errors import ApiError


ROLES = {"PlatformAdmin", "ClientAdmin", "LocationManager"}


def require_auth(allowed_roles):
    """
    Extract & validate auth headers, returning (role, user_id).
    Raises ApiError with the priority-ordered error id.
    """
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise ApiError("ERR_MISSING_AUTH_HEADERS", 401, "Missing X-User-Role or X-User-ID")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for endpoint")
    return role, uid
