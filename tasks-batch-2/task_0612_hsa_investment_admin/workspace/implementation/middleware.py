"""Auth / RBAC and request-helpers (PRD §2.1, §2.9).

Every request must carry X-User-ID and X-User-Role. If X-User-Role is missing
or not one of the recognized role names -> ERR_UNAUTHENTICATED (401). If the
role is recognized but not permitted for the operation -> ERR_FORBIDDEN (403).
Recognized roles: Accountholder, Employer, AccountAdmin.
"""
from flask import request

from errors import err

ROLES = {"Accountholder", "Employer", "AccountAdmin"}


def caller():
    """Return (user_id, role), enforcing ERR_UNAUTHENTICATED.

    Priority 1 (PRD §2.9): a missing or unrecognized role yields
    ERR_UNAUTHENTICATED. We require X-User-Role to be a recognized role.
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role")
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (PRD §2.9): ERR_FORBIDDEN if role not permitted."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s not permitted for this operation" % role)
