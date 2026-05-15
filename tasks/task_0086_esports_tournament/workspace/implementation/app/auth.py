"""Authentication & RBAC middleware.

Per PRD §2.1:
  - Required headers: X-User-ID, X-User-Role
  - Recognised roles: LeagueAdmin, TeamManager, Player, Referee
  - Missing header  -> ERR_AUTH_MISSING (401)
  - Unrecognised role -> ERR_AUTH_INVALID_ROLE (401)
  - Role not in allowed set for endpoint -> ERR_FORBIDDEN (403)
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {"LeagueAdmin", "TeamManager", "Player", "Referee"}


def _extract_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_AUTH_MISSING", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_AUTH_INVALID_ROLE", f"Unknown role: {role}")
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
                raise ApiError("ERR_FORBIDDEN", f"Role {role!r} not permitted for {request.path}.")
            return func(*args, **kwargs)
        return wrapped
    return decorator


def current_actor() -> tuple[str, str]:
    return getattr(g, "user_id", ""), getattr(g, "user_role", "")
