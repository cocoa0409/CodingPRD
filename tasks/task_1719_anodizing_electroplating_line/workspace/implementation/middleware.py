"""Auth header extraction, role checking, and ownership scoping."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_RESOURCE_NOT_OWNED,
    raise_err,
)

ROLES = {"Customer", "LineOperator", "LabChemist", "QCInspector", "EHSOfficer", "ShopManager"}

STAFF_ROLES = {"LineOperator", "LabChemist", "QCInspector", "EHSOfficer", "ShopManager"}


def get_auth():
    """Tier 1: header presence and role validity. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
        )
    return user_id, role


def require_roles(allowed):
    """Tier 1 + 2. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "Role %s is not permitted for this endpoint" % role)
    return user_id, role


def check_customer_owns(role, user_id, resource_customer_id):
    """Tier 3: Customer role may only access resources whose customer_id == X-User-ID."""
    if role == "Customer" and resource_customer_id != user_id:
        raise_err(ERR_RESOURCE_NOT_OWNED, "Customer may only access its own resources")
