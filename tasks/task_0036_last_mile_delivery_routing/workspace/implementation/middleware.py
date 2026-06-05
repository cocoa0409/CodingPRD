"""Auth header extraction and role checking."""
from functools import wraps

from flask import request, g

import errors
from errors import ApiError

VALID_ROLES = {"DispatchManager", "SortAssociate", "Driver", "CustomerServiceAgent"}


def authenticate():
    """Validate the mandatory user-context headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Missing or invalid user context headers.",
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate then enforce role membership."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    errors.ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    "Role not permitted for this operation.",
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
