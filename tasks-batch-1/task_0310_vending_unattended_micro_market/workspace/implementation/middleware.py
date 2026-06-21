"""Auth header extraction and role checking (PRD 2.1)."""
from functools import wraps

from flask import request

from errors import ApiError

KNOWN_ROLES = {"FieldOps", "RouteDriver", "HostManager", "FinanceClerk"}


def get_user_context():
    """Validate X-User-ID and X-User-Role headers (priority 1 auth check)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT",
                       "Missing or invalid user context headers")
    return user_id, role


def require_roles(*allowed):
    """Decorator: validate auth then enforce RBAC (priority 1 then 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user_context()
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE",
                               "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
