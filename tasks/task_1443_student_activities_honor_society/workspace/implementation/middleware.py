"""Auth header extraction and role checks (PRD section 2.1)."""

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ApiError

ROLES = ("ActivitiesDirector", "Advisor", "Officer", "Member")


def auth():
    """Validate X-User-ID / X-User-Role; return (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-ID and X-User-Role headers are required and the role must be recognized")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       f"Role {role} is not permitted for this endpoint")
