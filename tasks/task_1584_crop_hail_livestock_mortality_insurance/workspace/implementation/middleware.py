"""Auth middleware: X-User-ID / X-User-Role header validation and RBAC (PRD 2.1).

PlatformAdmin, Underwriter and ClaimsApprover identities are opaque operator
ids. Policyholder identity is the acting Grower's id; Adjuster identity is the
acting Adjuster's id (entity-backed roles).
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    HTTP_STATUS,
)

ROLES = {"PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover"}


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers (pipeline priority 1)."""
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
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "X-User-ID and X-User-Role headers are required and the role must be one of the declared roles",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce endpoint role membership (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
