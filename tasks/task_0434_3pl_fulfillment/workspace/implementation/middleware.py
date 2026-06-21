"""Auth header extraction and RBAC enforcement (PRD §2.1).

Every request carries X-User-ID and X-User-Role. If either is missing or
X-User-Role is not one of the eight known roles -> ERR_UNAUTHENTICATED (401).
If the role is valid but not permitted for the operation -> ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err

# The eight roles, spelled precisely per PRD §2.1.
KNOWN_ROLES = {
    "BillingClerk",
    "ClientUser",
    "ReceivingClerk",
    "WavePlanner",
    "PickOperator",
    "PackStation",
    "ShipStation",
    "ReturnsClerk",
}


def get_auth():
    """Return (user_id, role) after validating presence and known-role.

    Raises ERR_UNAUTHENTICATED if a header is missing/blank or role is unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown X-User-Role")
    return user_id, role


def require_roles(role, allowed):
    """Enforce that `role` is in the allowed set for the operation (403 otherwise)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
