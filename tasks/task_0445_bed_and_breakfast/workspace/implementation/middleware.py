"""Auth header extraction and RBAC (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. Recognized roles, spelled
exactly: Innkeeper, Guest, Housekeeper, FinanceManager.
Missing either header -> ERR_UNAUTHENTICATED.
Authenticated but not permitted -> ERR_FORBIDDEN.
"""
from flask import request

from errors import err

VALID_ROLES = {"Innkeeper", "Guest", "Housekeeper", "FinanceManager"}


def get_caller():
    """Return (user_id, role) after validating presence and role legality.

    PRD §2.1: a request missing either header is rejected with ERR_UNAUTHENTICATED.
    A role string that is not one of the four recognized roles is also treated as
    unauthenticated (it does not identify a recognized caller).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized role")
    return user_id, role


def require_role(role, allowed):
    """PRD §2.1: authenticated but not permitted -> ERR_FORBIDDEN."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s not permitted for this operation" % role)
