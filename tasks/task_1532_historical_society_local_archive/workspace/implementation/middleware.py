"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD §2.1 / §2.8 priorities 1-2:
  - both headers present and non-empty, else
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  - caller role in the endpoint's roles list, else
    ERR_INSUFFICIENT_PERMISSIONS (403). A non-empty but unrecognized role
    value is in no endpoint's list, so it fails here with 403.
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

ROLES = {
    "Registrar",
    "Archivist",
    "ReadingRoomStaff",
    "BoardOfficer",
    "VolunteerCoordinator",
    "Volunteer",
    "Researcher",
    "SystemAdmin",
}

# GET endpoints admit every recognized role ("Any" in PRD §4).
ANY_ROLE = tuple(sorted(ROLES))


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing or empty",
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (priority 1), then enforce role membership (2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    "Caller role is not in the endpoint's authorized list",
                    HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
