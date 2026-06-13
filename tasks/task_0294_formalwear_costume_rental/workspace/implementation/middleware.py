"""Auth header extraction and role checking (PRD §2.1, §2.6 ordering).

Mandatory headers: X-User-ID (acting principal) and X-User-Role (capacity).
Recognized roles spelled exactly: Customer, StoreClerk, StoreManager.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Customer", "StoreClerk", "StoreManager"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    Both headers must be present and X-User-Role must be a known role name.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    """Role-permission gate. Raise ERR_FORBIDDEN if role not in allowed set."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role not permitted to perform this operation")
