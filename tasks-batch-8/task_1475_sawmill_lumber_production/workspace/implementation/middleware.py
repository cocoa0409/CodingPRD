"""Auth header extraction and role checking (PRD section 2.1).

Every request carries X-User-ID and X-User-Role. Missing either header, or a
role value the system does not declare, is ERR_UNAUTHENTICATED (401). A role
not on the endpoint's authorized list is ERR_FORBIDDEN (403).
"""
from flask import request

from errors import ApiError

ROLES = [
    "Scaler",
    "Sawyer",
    "KilnOperator",
    "Grader",
    "SalesRep",
    "MillManager",
]

# All read endpoints are shared by every declared role.
ALL_ROLES = list(ROLES)


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
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
