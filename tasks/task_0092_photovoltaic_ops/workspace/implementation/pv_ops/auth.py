"""Auth/RBAC middleware and helpers."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import g, request

from pv_ops.errors import APIError, ERR_AUTH_REQUIRED, ERR_FORBIDDEN


VALID_ROLES = {"PlatformAdmin", "O&MEngineer", "FieldOperator", "FinanceOfficer"}


def parse_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise APIError(ERR_AUTH_REQUIRED, 401, "Missing X-User-ID or X-User-Role")
    if role not in VALID_ROLES:
        raise APIError(ERR_AUTH_REQUIRED, 401, "Unknown role")
    return user_id, role


def require_roles(*roles: str) -> Callable:
    allowed = set(roles)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = parse_auth()
            if allowed and role not in allowed:
                raise APIError(ERR_FORBIDDEN, 403, "Role not permitted")
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
