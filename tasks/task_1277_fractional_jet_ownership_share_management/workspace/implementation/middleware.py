"""Auth middleware: X-User-ID / X-User-Role header extraction and role checking
(PRD section 2.1)."""

from flask import request

from errors import ApiError

DECLARED_ROLES = {"ProgramAdmin", "FleetOps", "FinanceOps", "Owner"}

HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"

ALL_ROLES = ["ProgramAdmin", "FleetOps", "FinanceOps", "Owner"]


def get_auth():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_CONTEXT."""
    user_id = request.headers.get(HDR_USER_ID)
    role = request.headers.get(HDR_USER_ROLE)
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_CONTEXT",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(*allowed_roles):
    """Authenticate and enforce that the caller's role is in allowed_roles."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
