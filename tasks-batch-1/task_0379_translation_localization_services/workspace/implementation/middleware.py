"""Auth header extraction and RBAC. Headers and roles from PRD §2.1."""
from flask import request

from errors import err

VALID_ROLES = {"ProjectManager", "AccountsReceivable", "Client", "Translator", "Reviewer"}


def get_user_context():
    """Validate and return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-Role header missing or malformed")
    return user_id, role


def require_role(role, allowed):
    """Priority-2 role check. Ownership for entity-backed roles is checked at the route level."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE",
                  "Role %s is not permitted for this operation" % role)
