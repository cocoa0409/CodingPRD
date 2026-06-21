"""Auth header extraction and RBAC (PRD §2.1)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"RevenueManager", "ReservationsAgent", "GuestUser", "PortAgent", "system"}


def get_user_context():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def require_role(role, allowed):
    """Reject if the caller's role is not in the allowed set for the endpoint."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE")
