"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC."""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    HTTP_STATUS,
)

ROLES = {
    "PlatformAdmin",
    "ProductionManager",
    "RiggingSupervisor",
    "StructuralEngineer",
    "WarehouseChief",
    "SafetyInspector",
    "CrewChief",
    "ClientContact",
}

ALL_ROLES = tuple(sorted(ROLES))


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers.

    Raises ERR_UNAUTHENTICATED (401) when either header is missing/empty or
    the role is not one of the declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-Role is not a recognized role",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce role membership for the endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if "Any" not in allowed and role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN,
                    HTTP_STATUS[ERR_FORBIDDEN],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
