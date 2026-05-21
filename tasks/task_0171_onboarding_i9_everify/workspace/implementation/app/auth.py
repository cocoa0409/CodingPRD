"""Auth middleware: X-User-ID and X-User-Role header parsing and RBAC enforcement."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import request

from .errors import err_auth_missing, err_forbidden


VALID_ROLES = {"Employee", "HRStaff", "EmployerRep", "System"}


def get_principal():
    """Read X-User-ID and X-User-Role from request headers. Returns (user_id, role)
    or raises ERR_AUTH_MISSING when either is missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err_auth_missing()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise err_auth_missing()
    if role not in VALID_ROLES:
        raise err_auth_missing("X-User-Role is not a recognized role.")
    return user_id, role


def require_roles(*allowed_roles: str):
    """Decorator: require the principal to hold one of `allowed_roles`.

    Auth is checked before RBAC (priority 1 then 2)."""
    allowed = set(allowed_roles)

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_principal()
            if role not in allowed:
                raise err_forbidden()
            return fn(user_id, role, *args, **kwargs)
        return wrapper
    return decorator
