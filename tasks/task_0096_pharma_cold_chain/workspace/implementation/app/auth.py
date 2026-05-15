"""Authentication & RBAC middleware. PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {
    "WarehouseAdmin",
    "Receiver",
    "QAOfficer",
    "Picker",
    "RecallOfficer",
}


def _extract_auth() -> tuple[str, str]:
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    # Priority order from PRD §2.12: missing role first, then missing user
    if not role:
        raise ApiError("ERR_AUTH_MISSING_ROLE", "X-User-Role header missing.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_AUTH_MISSING_ROLE", f"Unknown role: {role!r}")
    if not user_id:
        raise ApiError("ERR_AUTH_MISSING_USER", "X-User-ID header missing.")
    return user_id, role


def require_auth(*allowed_roles: str) -> Callable:
    """Decorator: validates headers and ensures the role is in the allowed set."""
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
