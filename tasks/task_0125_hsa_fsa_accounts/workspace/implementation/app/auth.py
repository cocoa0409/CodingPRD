"""Auth middleware — extracts X-User-ID, X-User-Role, enforces role permissions."""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import g, request

from .errors import ApiError


VALID_ROLES = {"AccountHolder", "PlanAdministrator", "ClaimAdjudicator", "Auditor"}


def _read_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_FORBIDDEN", f"Unknown role: {role}.")
    return user_id, role


def require_auth(allowed_roles: Iterable[str]) -> Callable:
    """Decorator that enforces auth + role permission per the SCAFFOLD's RBAC matrix.

    Validation priorities (PRD §2.10):
      1. ERR_MISSING_AUTH — headers absent.
      2. ERR_FORBIDDEN  — role unknown or not allowed for this endpoint.
    """
    allowed = set(allowed_roles)

    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _read_auth()
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN", f"Role '{role}' is not permitted on this endpoint.")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
