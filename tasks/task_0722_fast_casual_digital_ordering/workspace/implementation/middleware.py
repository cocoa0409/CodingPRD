"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

ROLES = {"Customer", "StoreManager", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    """Endpoint-level role gate -> ERR_FORBIDDEN."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this endpoint.")


def require_owner(role, user_id, owner_customer_id):
    """Entity-backed Customer ownership check -> ERR_FORBIDDEN.

    StoreManager / PlatformAdmin are opaque identities and never owner-gated.
    """
    if role == "Customer" and user_id != owner_customer_id:
        raise err("ERR_FORBIDDEN", "Customer does not own this resource.")
