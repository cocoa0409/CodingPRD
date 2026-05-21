"""Auth middleware — extracts X-User-ID / X-User-Role and enforces RBAC."""
from __future__ import annotations

from functools import wraps
from typing import Any

from flask import g, request

from .errors import ApiError


VALID_ROLES = {"Rider", "AgencyOfficer", "EmployerAdmin", "Auditor"}


def _extract_identity() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise ApiError("ERR_AUTH_MISSING", "X-User-ID and X-User-Role headers are required")
    if user_role not in VALID_ROLES:
        raise ApiError("ERR_AUTH_INVALID_ROLE", f"Unknown role: {user_role}")
    return user_id, user_role


def require_auth(*allowed_roles: str):
    """Decorator: pulls auth headers, verifies role, and stores it on flask.g."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            user_id, user_role = _extract_identity()
            g.user_id = user_id
            g.user_role = user_role
            if allowed_roles and user_role not in allowed_roles:
                raise ApiError("ERR_FORBIDDEN", f"Role {user_role} not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
