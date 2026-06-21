"""Auth header extraction and role checking (PRD §2.1, §2.11)."""
from flask import request

import errors

VALID_ROLES = {"ClubManager", "BillingClerk", "Member"}


def get_auth():
    """Validate auth headers per PRD §2.1 (priorities 1 & 2).

    Priority 1: X-User-Role present and one of the declared roles -> else 401.
    Priority 2: X-User-ID present when role is Member -> else 401.

    Returns (role, user_id).
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated("X-User-Role missing or invalid")
    user_id = request.headers.get("X-User-ID")
    if role == "Member" and (user_id is None or user_id == ""):
        raise errors.unauthenticated("X-User-ID required for Member calls")
    return role, user_id


def require_roles(role, allowed):
    """Priority 3: acting role permitted for this operation (RBAC) -> else 403."""
    if role not in allowed:
        raise errors.unauthorized(f"Role {role} not permitted for this operation")
