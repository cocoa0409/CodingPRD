"""Auth context extraction and role checking (PRD §2.1, scaffold validations priority 1/3/5)."""
from flask import request
from errors import ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN

ROLES = [
    "WholesaleAdmin",
    "OperatorManager",
    "RoutePlanner",
    "WarehouseOps",
    "CreditAdjuster",
    "TelemetryGateway",
]


def get_auth():
    """Tier 1: X-User-ID and X-User-Role present and role declared. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and name a declared role",
        )
    return user_id, role


def require_role(role, allowed):
    """Tier 3: role listed in endpoint's roles."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")


def require_operator_ownership(role, user_id, operator_id):
    """Tier 5: OperatorManager may only act on its own operator's resources."""
    if role == "OperatorManager" and operator_id is not None and user_id != operator_id:
        raise ApiError(ERR_FORBIDDEN, 403, "OperatorManager acting on another operator's resource")
