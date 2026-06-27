"""Auth header extraction and RBAC checks (PRD §2.1, validations priority 1-2)."""
from flask import request

from errors import err

VALID_ROLES = {"SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk", "Guardian"}


def get_user_context():
    """Return (user_id, role). Raise ERR_MISSING_USER_CONTEXT (401) when either
    header is missing/blank or the role is not one of the four declared roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_MISSING_USER_CONTEXT", "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_USER_CONTEXT", "X-User-Role header missing or malformed")
    return user_id.strip(), role


def require_role(role, allowed):
    """Priority 2: role must be permitted for this operation."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
