"""Auth header extraction and role checking (PRD section 2.1).

Priority 1: X-User-ID and X-User-Role present and non-empty, else
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
Priority 2: role must be one of the six declared roles AND permitted for the
endpoint, else ERR_UNAUTHORIZED_ROLE (403).
"""
from flask import request

from errors import ApiError

ROLES = [
    "StarsAdmin",
    "StarsAnalyst",
    "QualityOps",
    "SurveyCoordinator",
    "IncentiveManager",
    "ComplaintsAuditor",
]

ALL_ROLES = list(ROLES)


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is not None:
        user_id = user_id.strip()
    if role is not None:
        role = role.strip()
    if not user_id or not role:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Role is not one of the declared roles"
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
