"""Auth/role extraction (PRD §2.1) and request-context helpers."""
from flask import request

from errors import err

VALID_ROLES = {"SalonManager", "FrontDeskAgent", "Technician", "Member"}


def require_user_context():
    """Priority 1 (PRD §2.7): X-User-ID and X-User-Role present and role known.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            "Missing or invalid X-User-ID / X-User-Role.",
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (PRD §2.7): role must be permitted for this operation."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
