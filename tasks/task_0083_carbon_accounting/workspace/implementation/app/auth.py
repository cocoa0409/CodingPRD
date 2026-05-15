"""Authentication and RBAC middleware."""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import g, request

from .errors import api_error


VALID_ROLES = {
    "PlatformAdmin",
    "DataSteward",
    "FactorManager",
    "Verifier",
    "Discloser",
}


def parse_auth():
    """Extract X-User-ID/X-User-Role; raise ERR_AUTH_REQUIRED if invalid."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise api_error("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_auth(roles: Iterable[str]):
    """Decorator: ensure auth headers are present and role is permitted."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = parse_auth()
            if role not in allowed:
                raise api_error("ERR_FORBIDDEN", f"Role {role} not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
