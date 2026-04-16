"""Auth header extraction and role checking."""

from flask import request
from errors import ApiError

VALID_ROLES = {"ShelterManager", "CaseWorker", "Veterinarian"}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError("ERR_AUTH_REQUIRED", "Authentication required", 401)
    return user_id, role


def require_role(*allowed_roles):
    """Check that the caller has one of the allowed roles."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", "Forbidden", 403)
    return user_id, role


def get_pagination():
    """Parse limit and offset query params with defaults."""
    try:
        limit = int(request.args.get("limit", 20))
    except (ValueError, TypeError):
        limit = 20
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
