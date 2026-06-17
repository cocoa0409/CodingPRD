"""Auth header extraction and role checking (PRD section 2.1, 2.9)."""
from flask import request

from errors import err

VALID_ROLES = {
    "Contractor",
    "Dispatcher",
    "YardAdmin",
    "ScaleOperator",
    "PermitOfficer",
    "BillingClerk",
}


def require_auth():
    """Validate presence/validity of X-User-ID and X-User-Role.

    Returns (user_id, role). Raises ERR_MISSING_AUTH_HEADERS (401) if either
    header is missing or malformed (role not among the six valid roles).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH_HEADERS",
                  "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    """Role authorization for the operation. Raises ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE",
                  "Role %s is not permitted for this operation" % role)
