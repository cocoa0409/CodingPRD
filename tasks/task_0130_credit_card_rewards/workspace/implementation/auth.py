"""Authentication and RBAC helpers."""
from functools import wraps

from flask import g, request

from constants import VALID_ROLES, ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN
from errors import err


def auth_middleware():
    """Validate X-User-ID / X-User-Role headers. Raises APIError on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID or X-User-Role header missing")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", f"Role '{role}' is not recognised")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed_roles):
    """Decorator: only permit listed roles to access this endpoint."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.role not in allowed:
                raise err("ERR_FORBIDDEN", f"Role '{g.role}' cannot access this endpoint")
            return fn(*args, **kwargs)

        return wrapped

    return deco


def is_cardholder() -> bool:
    return getattr(g, "role", None) == ROLE_CARDHOLDER


def is_admin() -> bool:
    return getattr(g, "role", None) == ROLE_PLATFORM_ADMIN
