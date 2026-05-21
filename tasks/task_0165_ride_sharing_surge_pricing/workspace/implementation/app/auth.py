"""Auth (X-User-ID + X-User-Role) and RBAC."""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Tuple

from flask import g, request

from .errors import err_auth_missing, err_forbidden

VALID_ROLES = {"Rider", "Driver", "PlatformAdmin", "DisputeOps"}


def authenticate() -> Tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_auth_missing()
    if role not in VALID_ROLES:
        raise err_auth_missing("Unknown X-User-Role")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(allowed: Iterable[str]):
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _user_id, role = authenticate()
            if role not in allowed_set:
                raise err_forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user() -> Tuple[str, str]:
    return g.user_id, g.user_role
