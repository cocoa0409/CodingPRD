"""Auth header extraction and role checking (PRD §2.1, §2.9 priorities 1-2)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"ClinicAdmin", "Scheduler", "Nephrologist", "BillingClerk"}


def require_auth():
    """Priority 1: X-User-ID and X-User-Role headers present and well-formed.

    Returns (user_id, role). Raises ERR_MISSING_USER_CONTEXT (400) if either
    header is missing/blank or the role is not one of the four known roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Missing X-User-ID or X-User-Role header.")
    if str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Blank X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", "Unknown X-User-Role value '%s'." % role)
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role must be permitted for this operation, else ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role '%s' is not permitted for this operation." % role)
