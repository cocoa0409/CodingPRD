"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC."""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    HTTP_STATUS,
)

ROLES = {
    "SystemOperator",
    "CapitalAnalyst",
    "RegulatorReviewer",
    "BoardApprover",
    "ExternalAuditor",
}


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "X-User-ID or X-User-Role header missing or malformed",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce role membership (priority 2).

    "Any" means any caller presenting one of the five recognized roles.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if "Any" in allowed:
                if role not in ROLES:
                    raise ApiError(
                        ERR_FORBIDDEN_FOR_ROLE,
                        HTTP_STATUS[ERR_FORBIDDEN_FOR_ROLE],
                        "Role not permitted for this endpoint",
                    )
            elif role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    HTTP_STATUS[ERR_FORBIDDEN_FOR_ROLE],
                    "Role not permitted for this endpoint",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
