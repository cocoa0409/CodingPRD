"""Authentication and role authorization (§2.1, rejection order items 1-2)."""

import functools

from flask import g, request

from constants import ALL_ROLES
from errors import ApiError


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require(*roles):
    """Decorator enforcing item 1 (authentication) then item 2 (role)."""
    allowed = list(roles) if roles else list(ALL_ROLES)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)
