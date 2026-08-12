"""Auth middleware (PRD 2.1): X-User-ID / X-User-Role headers and RBAC."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
)

ALL_ROLES = {
    "EventDirector",
    "RegistrationOfficer",
    "ScreeningOfficer",
    "TeamLead",
    "ProcurementOfficer",
    "Inspector",
    "LeadInspector",
    "HeadReferee",
    "Scorekeeper",
    "QueueManager",
    "FieldResetCrew",
    "JudgeAdvisor",
    "Judge",
    "TravelOfficer",
}

# Roles whose X-User-ID is the id of a persisted Person row.
ENTITY_BACKED_ROLES = {
    "TeamLead",
    "Inspector",
    "LeadInspector",
    "HeadReferee",
    "Scorekeeper",
    "Judge",
}


def require_roles(*roles):
    """Validate identity headers and endpoint role authorization.

    Priority 1: headers present and well-formed -> 400.
    Priority 2: role permitted for endpoint -> 403.
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not str(user_id).strip()
        or role is None
        or not str(role).strip()
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    role = role.strip()
    user_id = user_id.strip()
    if role not in ALL_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role value is not a recognised role",
        )
    if role not in roles:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            403,
            "Role %s is not permitted for this endpoint" % role,
        )
    return user_id, role
