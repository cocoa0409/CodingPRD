"""Auth middleware: header extraction and role validation."""
from flask import request
from errors import (
    APIError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    HTTP_STATUS,
)

VALID_ROLES = {
    "PlatformAdmin",
    "AccountManager",
    "FinanceApprover",
    "ProofApprover",
    "WarehouseOps",
    "ShippingOps",
}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED on missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, HTTP_STATUS[ERR_UNAUTHENTICATED])
    return user_id, role


def require_role(allowed):
    """Confirm caller has one of the allowed roles; return (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise APIError(ERR_FORBIDDEN_ROLE, HTTP_STATUS[ERR_FORBIDDEN_ROLE])
    return user_id, role
