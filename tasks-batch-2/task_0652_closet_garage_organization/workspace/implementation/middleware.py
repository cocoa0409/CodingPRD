"""Authentication and role extraction.

Headers (PRD 2.1):
  X-User-ID   — acting user id (for Customer this is the Customer.id)
  X-User-Role — one of Anonymous, Customer, Designer, Scheduler,
                ManufacturingOps, PlatformAdmin
"""
from flask import request

from errors import err

RECOGNIZED_ROLES = {
    "Anonymous", "Customer", "Designer", "Scheduler",
    "ManufacturingOps", "PlatformAdmin",
}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when missing/invalid.

    Both X-User-ID and X-User-Role must be present, and X-User-Role must be a
    recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED")
    return user_id, role


def require_roles(role, allowed):
    """Enforce RBAC: acting role must be in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE")
