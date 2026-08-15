"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC."""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    HTTP_STATUS,
)

ROLES = {
    "ProgramManager",
    "FixtureEngineer",
    "ConfigCoordinator",
    "ProductionPlanner",
    "WarehouseLead",
    "InstallCrewLead",
    "HotlineAgent",
    "StoreManager",
    "PlatformAdmin",
}


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers.

    Raises ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER) when either
    header is missing or empty.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "X-User-ID or X-User-Role header missing or empty",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce role membership.

    The special role name "Any" means any authenticated caller presenting one
    of the nine recognized roles may access. A role header value that is not
    one of the nine recognized roles fails the role check with 403.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if "Any" in allowed:
                if role not in ROLES:
                    raise ApiError(
                        ERR_INSUFFICIENT_PERMISSIONS,
                        HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                        "Role not permitted for this operation",
                    )
            elif role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
