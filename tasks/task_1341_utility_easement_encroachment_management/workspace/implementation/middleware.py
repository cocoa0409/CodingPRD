"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC."""

from __future__ import annotations

from functools import wraps

from flask import request

from constants import ALL_ROLES
from errors import ApiError, HTTP_STATUS


def get_auth() -> tuple[str, str]:
    """Extract and validate the identity headers (PRD section 2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "" or role not in ALL_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_ROLE",
            HTTP_STATUS["ERR_MISSING_OR_INVALID_ROLE"],
            "X-User-Role header missing or not a declared role",
        )
    if user_id is None or user_id.strip() == "":
        raise ApiError(
            "ERR_MISSING_OR_INVALID_ROLE",
            HTTP_STATUS["ERR_MISSING_OR_INVALID_ROLE"],
            "X-User-ID header missing or empty",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce role membership per endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED_ROLE",
                    HTTP_STATUS["ERR_UNAUTHORIZED_ROLE"],
                    "Role not permitted for this endpoint",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
