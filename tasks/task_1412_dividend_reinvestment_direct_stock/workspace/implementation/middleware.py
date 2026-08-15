"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = ("PlanAdmin", "Participant")
ADMIN = ["PlanAdmin"]
PARTICIPANT = ["Participant"]
ANY_ROLE = ["PlanAdmin", "Participant"]


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


def check_ownership(owner_participant_id, user_id, role):
    """Participant-role callers may only touch their own resources."""
    if role == "Participant" and owner_participant_id != user_id:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Participant may only access own resources"
        )
