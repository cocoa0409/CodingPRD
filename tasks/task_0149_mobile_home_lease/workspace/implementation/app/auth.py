"""Authentication and authorization helpers."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {"ParkManager", "Resident", "PlatformAdmin"}


def _extract_headers() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID", "").strip()
    user_role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not user_role:
        raise ApiError("ERR_AUTH_REQUIRED")
    return user_id, user_role


def require_auth(*allowed_roles: str) -> Callable:
    """Decorator: enforce that the request has valid auth headers and one of allowed_roles."""

    allowed = set(allowed_roles)

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id, user_role = _extract_headers()
            g.user_id = user_id
            g.user_role = user_role
            # Authorization
            if allowed and user_role not in allowed:
                raise ApiError("ERR_FORBIDDEN")
            # Role itself must be recognised; if not in VALID_ROLES treat as forbidden
            if user_role not in VALID_ROLES:
                raise ApiError("ERR_FORBIDDEN")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def current_user() -> tuple[str, str]:
    return getattr(g, "user_id", ""), getattr(g, "user_role", "")


__all__ = ["require_auth", "current_user", "VALID_ROLES"]
