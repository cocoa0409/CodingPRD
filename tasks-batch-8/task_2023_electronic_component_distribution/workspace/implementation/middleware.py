"""Auth context: X-User-ID / X-User-Role validation and role/ownership checks."""

from flask import request

import errors as E
from errors import ApiError

ROLES = {
    "DistributorAdmin",
    "SalesRep",
    "CustomerBuyer",
    "WarehouseOps",
    "QualityInspector",
    "SupplierAdmin",
}

ENTITY_BACKED_ROLES = {"CustomerBuyer"}


def require_auth():
    """Validate presence/shape of auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
        )
    return user_id, role


def require_role(user_id, role, allowed):
    if role not in allowed:
        raise ApiError(
            E.ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role not allowed for this endpoint.",
        )


def check_buyer_ownership(user_id, role, customer_id):
    """CustomerBuyer may act only on resources of their own customer account."""
    if role in ENTITY_BACKED_ROLES and customer_id != user_id:
        raise ApiError(
            E.ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "CustomerBuyer may only act on their own customer account's resources.",
        )
