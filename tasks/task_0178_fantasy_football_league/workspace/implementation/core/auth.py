"""Authentication and RBAC middleware."""
from __future__ import annotations

from functools import wraps
from typing import Tuple

from flask import g, request

from core.errors import err_auth_invalid_role, err_auth_missing, err_forbidden


VALID_ROLES = {"Commissioner", "Manager"}


def _extract_identity() -> Tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or role is None:
        raise err_auth_missing()

    user_id = user_id.strip()
    role = role.strip()

    if not user_id or not role:
        raise err_auth_missing()

    if role not in VALID_ROLES:
        raise err_auth_invalid_role(f"Unknown role: {role}")

    return user_id, role


def require_roles(*roles: str):
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_identity()
            g.user_id = user_id
            g.role = role
            if allowed and role not in allowed:
                raise err_forbidden(
                    f"Role {role} is not permitted for this endpoint."
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_auth():
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_identity()
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id() -> str:
    return g.user_id


def current_role() -> str:
    return g.role
