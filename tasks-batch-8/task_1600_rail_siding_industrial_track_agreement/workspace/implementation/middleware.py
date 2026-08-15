"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = [
    "RailroadContractsManager",
    "ShipperFacilityManager",
    "RailroadEngineer",
    "SafetyInspector",
    "RailroadServiceManager",
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
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Role not permitted for this endpoint"
        )
    return user_id, role


def require_shipper_party(user_id, agreement):
    """Shipper-side actions require X-User-ID == agreement.shipper_user_id."""
    if user_id != agreement.get("shipper_user_id"):
        raise ApiError(
            "ERR_NOT_AGREEMENT_PARTY",
            403,
            "Caller is not the agreement's shipper party",
        )
