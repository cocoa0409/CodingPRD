"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = ("AgencyAdmin", "AgencyAccountant", "Producer")

ADMIN = ["AgencyAdmin"]
ADMIN_ACCT = ["AgencyAdmin", "AgencyAccountant"]
ALL_ROLES = list(ROLES)
PRODUCER_ONLY = ["Producer"]


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role). Priority 1: both headers present and role declared.
    Priority 2: role authorized for the endpoint.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
