"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import ApiError

ROLES = ("PropertyManager", "LeasingAgent", "Applicant")

PM = "PropertyManager"
AGENT = "LeasingAgent"
APPLICANT = "Applicant"


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and the role must be "
            "one of PropertyManager, LeasingAgent, Applicant",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Role is not permitted to call this endpoint"
        )
    return user_id, role
