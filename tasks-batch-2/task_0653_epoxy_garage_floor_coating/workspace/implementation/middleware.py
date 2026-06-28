"""Auth header extraction and RBAC (SCAFFOLD §1.4 priorities 1-2 / PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"PlatformAdmin", "SalesRep", "Scheduler", "Crew", "WarrantyAgent", "Customer"}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role headers present and well-formed.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: acting role permitted for the operation (RBAC §1.7)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", f"Role {role} not permitted for this operation")
