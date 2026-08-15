"""Authentication and role authorization middleware (PRD sections 2.1, 2.8
gates 1-2). Identity headers: X-User-ID and X-User-Role."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED
from util import ROLES


def require_roles(*roles):
    """Validate identity headers, then check the caller's role membership."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError(
                    ERR_UNAUTHENTICATED,
                    401,
                    "X-User-ID and X-User-Role headers are required and the role "
                    "must be one of the five declared roles",
                )
            if role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN,
                    403,
                    "Role %s is not authorized for this operation" % role,
                )
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
