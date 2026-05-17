"""Authentication / RBAC primitives — header parsing + role helpers."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import request

from .errors import err_auth_required, err_forbidden

# Role spellings per PRD §2.1.
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_THERAPIST = "Therapist"
ROLE_SUPERVISOR = "Supervisor"
ROLE_BILLING_CLERK = "BillingClerk"

ALL_ROLES = {ROLE_PRACTICE_ADMIN, ROLE_THERAPIST, ROLE_SUPERVISOR, ROLE_BILLING_CLERK}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    """Extract & validate X-User-ID / X-User-Role; raises ERR_AUTH_REQUIRED on failure."""
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_auth_required(f"Headers {HEADER_USER_ID} and {HEADER_USER_ROLE} are required")
    if user_role not in ALL_ROLES:
        raise err_auth_required(f"Unknown role: {user_role}")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
    """Decorator: validate auth headers THEN check role is in `allowed`."""
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
