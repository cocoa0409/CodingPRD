"""Auth header extraction and role checking (PRD 2.1, scaffold validations 1-2)."""
from flask import request

from errors import ApiError

ROLES = [
    "AssociationAdmin",
    "Dispatcher",
    "Pilot",
    "VesselAgent",
    "FinanceOfficer",
    "Investigator",
]

# GET endpoints are readable by every declared role.
ANY_ROLE = list(ROLES)


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role). For role Pilot, user_id is the acting Pilot's id;
    for every other role it is an opaque operator identifier.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
