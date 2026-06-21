"""Auth header extraction and role checking (PRD section 2.1, 2.9)."""
from flask import request

from db import ROLES
from errors import err


def get_user_context():
    """Validate presence/validity of X-User-ID and X-User-Role headers.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    when either header is missing, empty, or carries an unrecognized role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID header missing or invalid")
    if not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-Role header missing or invalid")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role authorization. Raises ERR_INSUFFICIENT_PERMISSIONS."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role not permitted for this operation")
