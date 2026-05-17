"""Auth / RBAC primitives — X-User-ID + X-User-Role per PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import request

from .errors import err_insufficient_permissions, err_invalid_user_context

# Role names per PRD §2.1
ROLE_PAYROLL_SPECIALIST = "PayrollSpecialist"
ROLE_PAYROLL_MANAGER = "PayrollManager"
ROLE_TREASURER = "Treasurer"

ALL_ROLES = {ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    """Validate priority-1 (headers present) and priority-2 (role recognized)."""
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_invalid_user_context("X-User-ID and X-User-Role headers are required")
    if user_role not in ALL_ROLES:
        raise err_invalid_user_context(f"Unknown role: {user_role}")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
    """Decorator enforcing auth header presence and role permission.

    `Any` role in the scaffold is represented as "no role restriction" — pass
    no `allowed` args (or all three roles) to permit any authenticated user.
    """
    allowed_set = set(allowed) if allowed else ALL_ROLES

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_caller()
            if user_role not in allowed_set:
                raise err_insufficient_permissions(
                    f"Role '{user_role}' is not authorized for this endpoint"
                )
            kwargs["_caller_id"] = user_id
            kwargs["_caller_role"] = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_any_role() -> Callable:
    """Read-only operations — any of the three recognized roles."""
    return require_roles(*ALL_ROLES)
