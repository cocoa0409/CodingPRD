"""Auth header extraction and role checking (pipeline stages 1-2)."""
from functools import wraps

from flask import g, request

from errors import (ApiError, ERR_FORBIDDEN,
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
from util import ROLES

ANY = tuple(ROLES)


def current_user():
    return getattr(g, "user_id", None), getattr(g, "user_role", None)


def require_roles(*roles):
    """Validate X-User-ID / X-User-Role presence, then endpoint role access."""
    allowed = set(roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or uid.strip() == "" or role is None or role.strip() == "":
                raise ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                               "X-User-ID and X-User-Role headers are required")
            if role not in allowed:
                raise ApiError(ERR_FORBIDDEN, 403,
                               f"Role {role} is not permitted for this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
