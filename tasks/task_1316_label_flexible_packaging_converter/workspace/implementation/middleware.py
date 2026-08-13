"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = ["Estimator", "PrepressOperator", "PressOperator", "QualityManager"]

# Read-only retrieval of any resource is available to all four roles.
ALL_ROLES = list(ROLES)


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        not user_id
        or not isinstance(user_id, str)
        or not user_id.strip()
        or not role
        or role not in ROLES
    ):
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
