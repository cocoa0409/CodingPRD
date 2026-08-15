"""Auth header extraction and role checking (PRD §2.1)."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Caseworker", "ProgramManager", "FinanceOfficer", "Auditor"}

ALL_ROLES = ["Caseworker", "ProgramManager", "FinanceOfficer", "Auditor"]


def actor():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or invalid X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(allowed):
    """Return acting user_id if the role is authorized for this endpoint."""
    user_id, role = actor()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role is authenticated but not listed in the endpoint's roles")
    return user_id
