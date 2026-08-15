"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

PRD 2.1: every request carries X-User-ID and X-User-Role. A missing header or
an undeclared role value yields ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
(400). A declared role that is not permitted on the endpoint yields
ERR_UNAUTHORIZED_ROLE (403).
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
)

ROLES = {
    "NurseAdmin",
    "ChargeNurse",
    "StaffNurse",
    "FloatCoordinator",
    "Regulator",
}

ALL_ROLES = ("NurseAdmin", "ChargeNurse", "StaffNurse", "FloatCoordinator", "Regulator")


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or user_id.strip() == ""
        or role is None
        or role.strip() == ""
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Authenticate, then enforce that the declared role is in `allowed`."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED_ROLE,
                    "Acting role is not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
