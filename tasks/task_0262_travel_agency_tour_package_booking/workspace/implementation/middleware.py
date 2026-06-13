"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

KNOWN_ROLES = {"AgencyAdmin", "TravelAgent", "Customer", "Supplier"}


def get_user_context():
    """Validate the two mandatory headers. Returns (user_id, role).

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400) when either header
    is absent, empty, or X-User-Role is not a recognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be known.",
        )
    return user_id, role


def require_role(role, allowed):
    """Endpoint-level RBAC gate. Raises ERR_FORBIDDEN_FOR_ROLE (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Role not permitted for this operation.")
