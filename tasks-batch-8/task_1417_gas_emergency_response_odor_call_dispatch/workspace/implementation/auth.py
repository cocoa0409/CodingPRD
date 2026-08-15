"""Auth middleware (PRD §2.1): X-User-ID + X-User-Role headers, role gating."""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = {"SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator"}


def require_roles(*roles):
    """Validate user-context headers, then enforce endpoint role membership.

    Injects user_id and role as kwargs into the wrapped view.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers are required and the role must be declared",
                    400,
                )
            if roles and role not in roles:
                raise ApiError(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    "Role %s is not permitted on this endpoint" % role,
                    403,
                )
            kwargs["user_id"] = user_id
            kwargs["role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
