"""Auth / RBAC primitives — X-User-ID + X-User-Role per PRD §2.1."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import request

from .errors import err_auth_required, err_forbidden

# Canonical role names per PRD §2.1
ROLE_ORDERING_PROVIDER = "OrderingProvider"
ROLE_LAB_TECH = "LabTech"
ROLE_LAB_DIRECTOR = "LabDirector"

ALL_ROLES = {ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR}

# Map role -> required Clinician.role_kind enum value
ROLE_TO_ROLE_KIND = {
    ROLE_ORDERING_PROVIDER: "ORDERING_PROVIDER",
    ROLE_LAB_TECH: "LAB_TECH",
    ROLE_LAB_DIRECTOR: "LAB_DIRECTOR",
}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_auth_required(
            f"Headers {HEADER_USER_ID} and {HEADER_USER_ROLE} are required and non-empty"
        )
    if user_role not in ALL_ROLES:
        # Unknown role — still treat as forbidden (no permission anywhere)
        raise err_forbidden(f"Unknown role: {user_role}")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
    """Decorator: AUTH check (priority 1) -> FORBIDDEN check (priority 2)."""
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
