"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.8)."""
from functools import wraps

from flask import g, request

from errors import ApiError

VALID_ROLES = {"ClinicAdmin", "Provider"}


def extract_user_context():
    """Validate X-User-ID and X-User-Role. Raises on missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "Missing or invalid user context header")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: enforce auth (priority 1) then RBAC (priority 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = extract_user_context()
            if role not in allowed_roles:
                raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                               "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
