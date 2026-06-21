"""Auth header extraction and RBAC helpers per PRD section 2.1."""
from flask import request

from errors import err

KNOWN_ROLES = {"BoxOfficeAgent", "AccountHolder", "FinanceClerk"}


def get_auth():
    """Validate X-User-ID and X-User-Role. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED if either header is missing or the role is
    not one of the three known roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown user context")
    return user_id, role


def require_role(role, allowed):
    """RBAC check. Raises ERR_FORBIDDEN when role not in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted for this operation" % role)
