"""Auth + RBAC helpers."""
from functools import wraps
from flask import request

from errors import APIError


VALID_ROLES = {"Admin", "Supervisor", "Physician", "Nurse",
               "Caregiver", "Family", "Finance", "SystemSync"}


def get_caller():
    """Extract (user_id, role) from headers; raise ERR_AUTH_MISSING on missing/bad."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise APIError("ERR_AUTH_MISSING", "X-User-ID and X-User-Role required", 401)
    if not isinstance(user_id, str) or not user_id.strip():
        raise APIError("ERR_AUTH_MISSING", "X-User-ID malformed", 401)
    if role not in VALID_ROLES:
        raise APIError("ERR_AUTH_MISSING", f"X-User-Role '{role}' is not a recognized role", 401)
    return user_id.strip(), role


def require_roles(*allowed_roles):
    """Decorator that authenticates and then enforces role membership."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_caller()
            if role not in allowed_roles:
                raise APIError("ERR_FORBIDDEN",
                               f"Role {role} not permitted for this endpoint",
                               403)
            return fn(user_id, role, *args, **kwargs)
        return wrapper
    return decorator
