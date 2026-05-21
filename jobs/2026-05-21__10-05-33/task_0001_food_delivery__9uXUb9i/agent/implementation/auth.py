"""RBAC and identity header parsing (PRD §2.1)."""
from __future__ import annotations

from functools import wraps
from flask import request, g

from errors import ApiError


ALLOWED_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def parse_auth() -> tuple[str, str]:
    """Returns (user_id, role). Raises ApiError on missing/invalid headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALLOWED_ROLES:
        raise ApiError("ERR_AUTH_REQUIRED")
    return user_id, role


def require_roles(*roles: str):
    """Decorator enforcing PRD §2.1: header presence then role allowlist."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = parse_auth()
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
