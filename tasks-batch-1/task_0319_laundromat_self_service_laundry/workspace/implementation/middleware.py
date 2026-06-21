"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Manager", "Attendant", "Member"}


def get_identity():
    """Extract and validate X-User-ID / X-User-Role headers (PRD §2.1).

    A request missing either header, or carrying an X-User-Role that is not one
    of the three known roles, is rejected with ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """Authorization (PRD §2.10 step 2): role must be permitted, else 403."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role not permitted to perform this operation")
