"""Auth header extraction and RBAC (PRD §2.1)."""

from flask import request

from errors import ApiError, ERR_MISSING_USER_CONTEXT, ERR_FORBIDDEN_FOR_ROLE

VALID_ROLES = {"TravelManager", "Traveler", "Approver", "FinanceOfficer", "System"}


def authenticate(allowed_roles):
    """Validate the user-context headers and role permission.

    (1) presence/validity of X-User-ID and X-User-Role -> ERR_MISSING_USER_CONTEXT
    (2) role permitted for this endpoint -> ERR_FORBIDDEN_FOR_ROLE
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(ERR_MISSING_USER_CONTEXT, 400,
                       "Missing or malformed user-context headers")
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403,
                       "Caller role not permitted for this endpoint")
    return user_id, role
