"""Authentication & RBAC middleware per PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {"TrainingAdmin", "CourseDesigner", "DepartmentManager", "Trainee"}


def _extract_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE", f"Unknown role: {role!r}")
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
                raise ApiError("ERR_FORBIDDEN_ROLE", f"Role {role!r} not permitted for {request.path}.")
            return func(*args, **kwargs)
        return wrapped
    return decorator


def optional_auth(func: Callable) -> Callable:
    """Decorator for endpoints that may or may not be authenticated (public verification)."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        user_id = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        g.user_id = user_id or ""
        g.user_role = role or ""
        return func(*args, **kwargs)
    return wrapped


def current_actor() -> tuple[str, str]:
    return getattr(g, "user_id", ""), getattr(g, "user_role", "")
