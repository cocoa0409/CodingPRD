"""Auth header extraction + RBAC (PRD §2.1, §2.9).

Auth headers: X-User-ID (acting user id), X-User-Role (one of FrontDesk,
FinanceManager, Stylist, Member). Missing/malformed -> ERR_MISSING_AUTH_CONTEXT
(401). Role not permitted -> ERR_FORBIDDEN_ROLE (403).
"""

from flask import request

import errors
from errors import err

VALID_ROLES = {"FrontDesk", "FinanceManager", "Stylist", "Member"}


def get_auth():
    """Returns (user_id, role). Raises ERR_MISSING_AUTH_CONTEXT if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(errors.ERR_MISSING_AUTH_CONTEXT, "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err(errors.ERR_MISSING_AUTH_CONTEXT, "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_AUTH_CONTEXT, "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role authorisation. allowed is a set/list of role names."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
