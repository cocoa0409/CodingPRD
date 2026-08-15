"""Auth header extraction and role checking (validation priorities 1, 2, 5)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_CASE_ATTENDING

ROLES = {
    "URNurse",
    "AttendingPhysician",
    "PhysicianAdvisor",
    "PayerReviewer",
    "CaseManager",
    "AppealsCoordinator",
    "URDirector",
}

ANY_AUTHENTICATED = sorted(ROLES)


def get_actor():
    """Priority 1: both headers present and role recognized."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or unrecognized authentication headers", 401)
    return user_id, role


def require_roles(allowed):
    """Priority 2: role listed for the endpoint."""
    user_id, role = get_actor()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_ROLE, f"Role {role} is not authorized for this endpoint", 403)
    return user_id, role


def check_attending_ownership(case, user_id):
    """Priority 5: X-User-ID must equal case.attending_physician_id."""
    if case["attending_physician_id"] != user_id:
        raise ApiError(
            ERR_NOT_CASE_ATTENDING,
            "Caller is not the attending physician of record for this case",
            403,
        )
