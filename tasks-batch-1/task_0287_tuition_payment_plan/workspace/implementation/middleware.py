"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"Registrar", "Bursar", "Student"}


def get_user_context():
    """Validate X-User-ID and X-User-Role headers.

    PRD §2.1: every request must carry both headers. Missing or malformed ->
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """PRD §2.1: role not permitted for the operation -> ERR_FORBIDDEN_FOR_ROLE (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE",
                  "Role %s is not permitted for this operation" % role)
