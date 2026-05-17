"""Auth / RBAC primitives — X-User-ID + X-User-Role per PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import request

from .errors import err_auth_invalid_role, err_auth_missing, err_forbidden

# Canonical role names per PRD §2.1
ROLE_PARTICIPANT = "Participant"
ROLE_CUSTODIAN = "Custodian"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_AUDITOR = "Auditor"

ALL_ROLES = {ROLE_PARTICIPANT, ROLE_CUSTODIAN, ROLE_COMPLIANCE, ROLE_AUDITOR}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    """Validate priority-1 (headers present) and priority-2 (role recognized).

    Returns (user_id, role). Raises APIError otherwise.
    """
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_auth_missing()
    if user_role not in ALL_ROLES:
        raise err_auth_invalid_role(f"Unknown role: {user_role}")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
    """Decorator that enforces priorities 1, 2, and 3 of the validation table.

    Priority 1: ERR_AUTH_MISSING when either header is missing/empty.
    Priority 2: ERR_AUTH_INVALID_ROLE when role string is not recognized.
    Priority 3: ERR_FORBIDDEN when the (recognized) role is not authorized
                for this route.
    """
    allowed_set = set(allowed)

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_caller()
            if user_role not in allowed_set:
                raise err_forbidden(f"Role '{user_role}' is not authorized for this endpoint")
            kwargs["_caller_id"] = user_id
            kwargs["_caller_role"] = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
