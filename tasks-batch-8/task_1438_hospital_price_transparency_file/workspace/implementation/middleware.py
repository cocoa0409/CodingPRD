"""Auth middleware: X-User-ID / X-User-Role validation and RBAC (PRD 2.1).

Priority 1: headers present and non-empty -> else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
Priority 2: role permitted for the endpoint -> else ERR_FORBIDDEN_ROLE (403).
An unrecognized role value is permitted for nothing, so it fails priority 2.
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    HTTP_STATUS,
)

ROLES = {
    "PlatformAdmin",
    "ContractManager",
    "TransparencyOfficer",
    "ComplianceAuditor",
    "Consumer",
}

ALL_ROLES = ("PlatformAdmin", "ContractManager", "TransparencyOfficer", "ComplianceAuditor", "Consumer")


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (P1), then enforce role membership (P2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_ROLE,
                    HTTP_STATUS[ERR_FORBIDDEN_ROLE],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
