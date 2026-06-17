"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import ApiError

# The system recognizes exactly four roles (PRD §2.1).
KNOWN_ROLES = {"SalesAssociate", "ServiceAdvisor", "ShopManager", "Customer"}


def authenticate():
    """Priority 1: X-User-ID + X-User-Role present and role known.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown user context.")
    return user_id, role


def require_roles(role, allowed):
    """Priority 2: acting role must be permitted for this endpoint.

    ShopManager is a hierarchical override: it may perform any operation a
    SalesAssociate may perform (PRD §2.1). So if SalesAssociate is allowed,
    ShopManager is implicitly allowed too.
    """
    effective = set(allowed)
    if "SalesAssociate" in effective:
        effective.add("ShopManager")
    if role not in effective:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint.")
