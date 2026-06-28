"""Auth header extraction and RBAC checks (PRD §2.1, §2.10)."""
from flask import request

from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN_FOR_ROLE

# PRD §2.1: four roles. `system` is internal automation and is never an HTTP
# caller, so no externally submitted request may present `system` in X-User-Role.
HTTP_ROLES = {"ProgramManager", "GivingAdmin", "Employee"}


def get_user_context():
    """Return (user_id, role) after validating both headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID header missing or malformed")
    if not role or role not in HTTP_ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-Role header missing or malformed")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role-permission check (ERR_FORBIDDEN_FOR_ROLE)."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_FOR_ROLE,
                  "Caller role not permitted for this endpoint")
