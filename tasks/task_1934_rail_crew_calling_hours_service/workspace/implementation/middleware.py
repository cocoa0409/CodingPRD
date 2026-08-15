"""Auth header extraction, role checking, ownership checks (PRD §2.1)."""
from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_NOT_RESOURCE_OWNER,
)

ROLES = ("Employee", "CrewCaller", "CrewManager")


def auth():
    """Validate X-User-ID / X-User-Role; return (user_id, role)."""
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-ID and X-User-Role headers are required.",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED, 401,
            "X-User-Role must be one of: Employee, CrewCaller, CrewManager.",
        )
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE, 403,
            "Role '%s' is not permitted to perform this operation." % role,
        )


def require_owner(uid, employee_ref):
    """Entity-backed Employee ownership check (PRD §2.1)."""
    if uid != employee_ref:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER, 403,
            "X-User-ID does not match the employee this operation targets.",
        )
