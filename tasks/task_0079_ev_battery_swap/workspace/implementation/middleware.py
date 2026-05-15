"""Auth header extraction and role checking."""

from functools import wraps

from flask import g, request

from errors import (
    ERR_AUTH_REQUIRED,
    ERR_FORBIDDEN,
    raise_error,
)


VALID_ROLES = {"Member", "StationOperator", "PlatformAdmin"}


def auth_required(allowed_roles):
    """Decorator: validates auth headers and role membership."""
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get("X-User-ID", "")
            user_role = request.headers.get("X-User-Role", "")
            if not user_id or not user_role:
                raise_error(ERR_AUTH_REQUIRED, "Missing X-User-ID or X-User-Role header")
            if user_role not in VALID_ROLES:
                raise_error(ERR_FORBIDDEN, "Unknown role")
            if user_role not in allowed_set:
                raise_error(ERR_FORBIDDEN, "Role not permitted for this endpoint")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)
        return wrapped
    return deco
