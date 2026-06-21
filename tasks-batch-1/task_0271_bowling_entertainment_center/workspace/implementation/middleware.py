"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.6).

Headers (PRD §2.1):
  X-User-ID   — acting user id (the Customer.id when role is Customer; opaque otherwise)
  X-User-Role — one of: Customer, FrontDesk, LeagueAdmin, CenterManager
"""
from flask import request

from errors import err

ROLES = {"Customer", "FrontDesk", "LeagueAdmin", "CenterManager"}


def get_identity():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED on missing/invalid role.

    Per PRD §2.1: a request missing X-User-Role, or carrying a role outside the
    recognized set, is rejected with ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """RBAC: ERR_FORBIDDEN when role not in the allowed set for the operation."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
