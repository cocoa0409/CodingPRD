"""Auth header extraction and role checking (PRD §2.1, validation priorities 1-2)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

DECLARED_ROLES = {
    "CarrierOps",
    "AgencyDispatcher",
    "Pilot",
    "CarrierFinance",
    "AgencyFinance",
    "CardingInspector",
    "SystemAdmin",
}

ALL_BUSINESS_ROLES = [
    "CarrierOps",
    "AgencyDispatcher",
    "Pilot",
    "CarrierFinance",
    "AgencyFinance",
    "CardingInspector",
]


def actor():
    """Validate auth headers and return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "X-User-ID / X-User-Role headers missing, or role not a declared role",
            401,
        )
    return user_id, role


def require_roles(allowed):
    """Priority 1 then 2: authenticate, then check the endpoint's role list."""
    user_id, role = actor()
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "role authenticated but not in the endpoint's roles list",
            403,
        )
    return user_id, role
