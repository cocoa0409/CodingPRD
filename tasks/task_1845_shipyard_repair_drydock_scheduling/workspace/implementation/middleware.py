"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Header names, the seven declared roles, and per-endpoint role lists are read
from SCAFFOLD.yaml validations[1..2] and the endpoint table (PRD section 2.1).
"""

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
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
    "Subcontractor",
}


def get_auth() -> tuple[str, str]:
    """Extract and validate the identity headers (validation rung 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-ID or X-User-Role header missing",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-Role is not a declared role",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (rung 1), then enforce role membership (rung 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN,
                    HTTP_STATUS[ERR_FORBIDDEN],
                    "Role is not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
