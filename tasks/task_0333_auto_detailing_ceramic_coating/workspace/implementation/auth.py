"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.9, §1.7).

Headers: X-User-ID and X-User-Role (both mandatory). Roles: Customer,
Detailer, Scheduler, ShopManager. Customer is entity-backed (X-User-ID is the
acting Customer.id); the other three are opaque operator identities.
"""
from flask import request

from errors import err

ROLES = {"Customer", "Detailer", "Scheduler", "ShopManager"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if headers are missing
    or the role is not a recognized role (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE if the authenticated role is not in the allowed set (priority 2)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")


def require_owner(role, user_id, owner_customer_id):
    """For an entity-backed Customer acting on its own resource, X-User-ID must
    equal the resource's customer_id (priority 3). Opaque roles are exempt."""
    if role == "Customer" and user_id != owner_customer_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer does not own this resource")
