"""Auth header extraction and role checking.

PRD §2.1: every request carries X-User-ID and X-User-Role. Missing/malformed
either -> ERR_UNAUTHENTICATED (401). The four roles are RevenueManager,
FrontDeskAgent, NightAuditor, Guest. A role not permitted for the operation
-> ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err

VALID_ROLES = {"RevenueManager", "FrontDeskAgent", "NightAuditor", "Guest"}


def authenticate():
    """Validate the two auth headers. Returns (user_id, role) or raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN unless `role` is in the allowed set/iterable."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation" % role)
