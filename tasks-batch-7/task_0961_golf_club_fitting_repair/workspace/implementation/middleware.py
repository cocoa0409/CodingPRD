"""Auth header extraction and role checking."""
from flask import request

from errors import raise_err

VALID_ROLES = {
    "Customer",
    "FittingSpecialist",
    "RepairTechnician",
    "Instructor",
    "ShopManager",
    "ShopAdmin",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise_err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers are required")
    if not str(user_id).strip() or not str(role).strip():
        raise_err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers must be non-empty")
    if role not in VALID_ROLES:
        # Unknown role is treated as forbidden for any endpoint.
        raise_err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise_err("ERR_FORBIDDEN_ROLE", "Role not permitted for this endpoint")
