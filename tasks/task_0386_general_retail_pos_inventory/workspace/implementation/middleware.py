"""Auth header extraction and RBAC (PRD §2.1, §3.13)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

# PRD §2.1: exactly four recognized roles, spelled precisely.
RECOGNIZED_ROLES = {"StoreManager", "Cashier", "InventoryClerk", "Customer"}


def auth_context():
    """Return (user_id, role) after validating the role header.

    PRD §2.1: every request must carry X-User-ID and X-User-Role. A request
    that omits X-User-Role or presents a value that is not one of the four
    recognized roles is rejected with ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in RECOGNIZED_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """PRD §2.1: authenticated but not permitted -> ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
