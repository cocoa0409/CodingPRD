"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.12)."""
from flask import request

from errors import ApiError

KNOWN_ROLES = {"ProgramAdmin", "Inspector", "Caseworker"}


def get_auth():
    """Validate auth headers. Returns (user_id, role). Raises on failure.

    Priority 1: X-User-ID and X-User-Role present and role is known.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_AUTH", "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    """Priority 2: acting role must be permitted for the endpoint."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted to invoke this operation.")
