"""Auth header extraction and role checking."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

DECLARED_ROLES = {
    "PlantAdmin",
    "Planner",
    "LineOperator",
    "QALead",
    "Driver",
    "StoreReceiver",
    "ThriftClerk",
    "PricingAnalyst",
}


def get_auth():
    """Priority 1: X-User-ID and X-User-Role present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be declared",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role permitted for endpoint."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            f"Role {role} is not permitted for this endpoint",
            403,
        )
