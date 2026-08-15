"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD section 2.1: both headers are mandatory on every request; the role
must name one of the four declared roles (Any is a pseudo-role marking
read-only endpoints, never a real header value). VendorOperator identity is
the acting SurveyVendor's id; UnitManager identity is the acting CareUnit's
id; ProgramAdmin and DataSteward identities are opaque.
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    HTTP_STATUS,
)

ROLES = {"ProgramAdmin", "DataSteward", "VendorOperator", "UnitManager"}

ANY_AUTHENTICATED = "Any"


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers (priority 1)."""
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
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce endpoint role membership (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if ANY_AUTHENTICATED not in allowed and role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_ROLE,
                    HTTP_STATUS[ERR_FORBIDDEN_ROLE],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
