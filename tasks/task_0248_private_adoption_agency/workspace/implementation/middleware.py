"""Auth header extraction and RBAC checks (PRD §2.1, §1.7)."""
from flask import request

import errors

VALID_ROLES = {
    "AgencyAdmin",
    "Supervisor",
    "Caseworker",
    "FinanceOfficer",
    "CompactAdministrator",
}


def require_user():
    """Validate X-User-ID and X-User-Role presence/well-formedness.

    Returns (user_id, role). Raises ERR_MISSING_USER_CONTEXT when either header
    is missing, blank, or the role is not one of the five recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.err(errors.ERR_MISSING_USER_CONTEXT,
                         "X-User-ID and X-User-Role headers are required.")
    if not user_id.strip() or not role.strip():
        raise errors.err(errors.ERR_MISSING_USER_CONTEXT,
                         "X-User-ID and X-User-Role headers must be non-empty.")
    if role not in VALID_ROLES:
        raise errors.err(errors.ERR_MISSING_USER_CONTEXT,
                         "X-User-Role is not a recognized role.")
    return user_id.strip(), role


def require_role(role, allowed):
    """Raise ERR_UNAUTHORIZED if `role` is not in the `allowed` collection."""
    if role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED,
                         "Role is not permitted to perform this operation.")
