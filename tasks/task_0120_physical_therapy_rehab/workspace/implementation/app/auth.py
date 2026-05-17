"""Authentication / RBAC primitives."""
from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import request

from .errors import err_auth_missing, err_forbidden

ROLE_CLINIC_ADMIN = "ClinicAdmin"
ROLE_THERAPIST = "Therapist"
ROLE_BILLER = "Biller"
ROLE_PATIENT = "Patient"

ALL_ROLES = {ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER, ROLE_PATIENT}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def get_caller() -> tuple[str, str]:
    user_id = request.headers.get(HEADER_USER_ID, "")
    user_role = request.headers.get(HEADER_USER_ROLE, "")
    if not user_id or not user_role:
        raise err_auth_missing(f"Headers {HEADER_USER_ID} and {HEADER_USER_ROLE} are required")
    return user_id, user_role


def require_roles(*allowed: str) -> Callable:
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
