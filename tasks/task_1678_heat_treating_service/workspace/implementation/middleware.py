"""Auth: X-User-ID / X-User-Role header extraction and role gating."""
from flask import request, g

from errors import ApiError

ROLES = [
    "CustomerServiceRep",
    "ShopScheduler",
    "FurnaceOperator",
    "CalibrationTech",
    "QualityEngineer",
    "NadcapAuditor",
    "Customer",
]

ANY_ROLES = list(ROLES)


def get_context():
    """Validation priority 1: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not uid.strip() or not role or not role.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required and must be non-empty")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    """Validation priority 2: role permitted for this endpoint."""
    role = getattr(g, "user_role", None)
    if role is None:
        _, role = get_context()
    if role not in allowed:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "Role %s is not permitted on this endpoint" % role)


def check_ownership(customer_id):
    """Validation priority 3: Customer-role callers may only touch their own resources."""
    if g.user_role == "Customer" and g.user_id != customer_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Customer-role caller may only access resources they own")
