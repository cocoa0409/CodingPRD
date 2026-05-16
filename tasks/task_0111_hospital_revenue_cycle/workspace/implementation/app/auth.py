"""Authentication & RBAC middleware. PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {
    "RegistrationClerk",
    "ChargeCaptureClerk",
    "Coder",
    "Biller",
    "TestHarness",
}


def _extract_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_AUTH_MISSING", "Missing X-User-ID or X-User-Role header.")
    return user_id, role


def require_auth(*allowed_roles: str) -> Callable:
    """Decorator: validates headers and ensures the role is in the allowed set.

    Role validity is checked together with permission: an unknown role for a given
    endpoint produces ERR_FORBIDDEN (auth headers were present, but the role is not
    authorized for this endpoint per PRD §2.1).
    """
    allowed = set(allowed_roles) if allowed_roles else set(VALID_ROLES)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapped(*args, **kwargs):
            user_id, role = _extract_auth()
            g.user_id = user_id
            g.user_role = role
            if role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN",
                    f"Role {role!r} not permitted for {request.path}.",
                )
            return func(*args, **kwargs)

        return wrapped

    return decorator


def current_actor() -> tuple[str, str]:
    return getattr(g, "user_id", ""), getattr(g, "user_role", "")
