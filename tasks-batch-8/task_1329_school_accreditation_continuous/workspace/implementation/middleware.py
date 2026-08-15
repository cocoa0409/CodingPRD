"""Auth header extraction and role checking (PRD section 2.1).

The API uses two mandatory headers on every request:
  X-User-ID   - acting user identifier (Reviewer entity id when role=Reviewer;
                opaque otherwise)
  X-User-Role - one of the six declared roles below.
"""
from flask import request

from errors import ApiError

ROLES = [
    "AccreditationOfficer",
    "AccreditationCommission",
    "SchoolLeader",
    "Reviewer",
    "SystemBursar",
    "Anonymous",
]

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
            "Missing or malformed X-User-Role / X-User-ID headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
