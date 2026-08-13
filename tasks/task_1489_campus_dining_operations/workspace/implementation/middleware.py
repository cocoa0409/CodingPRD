"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = [
    "DiningAdmin",
    "HallManager",
    "KitchenLead",
    "Dietitian",
    "HealthInspector",
    "ContractManager",
    "DepartmentUser",
]

ALL_ROLES = list(ROLES)


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Tier 1: headers present, non-blank, recognized role -> ERR_UNAUTHENTICATED.
    Tier 2: role in endpoint's authorized set -> ERR_FORBIDDEN.
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "Missing or blank X-User-ID / X-User-Role headers",
        )
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Unrecognized role name")
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
