"""Auth header extraction and role checking (PRD 2.1, ladder rungs 1-3)."""

from flask import request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "ComplianceOfficer",
    "BoardChair",
    "EligibilityVerifier",
    "PatientServicesRep",
    "BillingSpecialist",
    "ProjectOfficer",
)

ALL_ROLES = ROLES


def authorize(*allowed_roles):
    """Rungs 1, 2 and 3 of the precedence ladder.  Returns the acting user id."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id
