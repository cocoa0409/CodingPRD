"""Auth header extraction and role checking (per PRD §2.1)."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_OWNER

ROLES = {
    "Customer",
    "IntakeAgent",
    "DepotTechnician",
    "DepotManager",
    "WarrantyAdministrator",
    "EngineeringLead",
}


def actor():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role / X-User-ID headers", 401)
    return user_id, role


def require_roles(*allowed):
    user_id, role = actor()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, "Role not permitted on this endpoint", 403)
    return user_id, role


def check_owner(user_id, role, owner_customer_id):
    """Customer role may only act on resources whose customer_id == X-User-ID."""
    if role == "Customer" and owner_customer_id != user_id:
        raise ApiError(ERR_NOT_OWNER, "Customer may only act on own resources", 403)
