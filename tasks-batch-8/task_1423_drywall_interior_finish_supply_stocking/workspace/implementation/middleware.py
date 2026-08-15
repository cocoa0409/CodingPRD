"""Auth header extraction and role checking."""
from flask import request
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "CreditManager",
    "EstimatorUser",
    "DispatcherUser",
    "Foreman",
    "ContractorAdmin",
    "AccountsReceivableUser",
    "WarehouseManager",
}


def get_role():
    """Validate X-User-Role header. Returns the role string or raises."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header", 401)
    return role


def require_roles(*allowed):
    """Check authentication then authorization."""
    role = get_role()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, f"Role {role} is not permitted on this endpoint", 403)
    return role
