"""Auth header extraction and role checking (PRD 2.1, validations 1-2)."""
from flask import request

from errors import ApiError, ERR_MISSING_AUTH, ERR_UNAUTHORIZED_ROLE

ROLES = {
    "PlantController",
    "QualityAssuranceManager",
    "LabTechnician",
    "PasteurizerOperator",
    "StateInspector",
}


def require_roles(*roles):
    """Validate X-User-ID / X-User-Role headers, then endpoint role permission.

    Returns the caller's X-User-ID (opaque operator id).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not user_id.strip()
        or role is None
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_AUTH,
            401,
            "X-User-Role or X-User-ID header absent or malformed",
        )
    if role not in roles:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            403,
            "Role '%s' is not permitted for this endpoint" % role,
        )
    return user_id
