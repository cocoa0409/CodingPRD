"""Auth middleware and RBAC enforcement.

§1.4 priority order:
  1. ERR_AUTH_REQUIRED — headers missing
  2. ERR_INVALID_ROLE — role not one of {Employee, Supervisor, PayrollAdmin}
  3. ERR_FORBIDDEN — role lacks permission for the endpoint
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Tuple

from flask import request

from .errors import err_auth_required, err_invalid_role, err_forbidden


VALID_ROLES = {"Employee", "Supervisor", "PayrollAdmin"}


def get_principal() -> Tuple[str, str]:
    """Read and validate the X-User-ID / X-User-Role headers.

    Raises ERR_AUTH_REQUIRED if either is missing (priority 1).
    Raises ERR_INVALID_ROLE if the role is not in the allowed set (priority 2).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        raise err_auth_required()
    if role not in VALID_ROLES:
        raise err_invalid_role()
    return user_id, role


def require_roles(*allowed_roles: str):
    """Decorator: require the principal to hold one of `allowed_roles`.

    Order: auth header presence → role validity → RBAC permission.
    """
    allowed = set(allowed_roles)

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_principal()
            if role not in allowed:
                raise err_forbidden()
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator
