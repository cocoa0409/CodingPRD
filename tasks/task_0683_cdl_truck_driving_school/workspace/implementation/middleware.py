"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD validations 1 & 2)."""
from functools import wraps

from flask import request, g

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"SchoolAdmin", "Registrar", "Instructor", "ThirdPartyExaminer"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID header")
    if not user_role or user_role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-Role header")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*roles):
    """Decorator factory: authenticate, then enforce RBAC (priority 2)."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise ApiError(ERR_FORBIDDEN, 403,
                               "Acting role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
