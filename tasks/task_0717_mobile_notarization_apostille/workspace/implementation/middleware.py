"""Auth header extraction and RBAC enforcement."""
from flask import request

import errors

VALID_ROLES = {"CoordinatorOps", "Notary", "ApostilleClerk", "Viewer"}


def require_auth(allowed_roles):
    """Validate X-User-Role (priority 1) then RBAC (priority 2).

    Returns (user_id, role). Raises ApiError on failure.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role header")
    if role not in allowed_roles:
        errors.fail(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
    return user_id, role


# Convenience role sets
ALL_ROLES = ["CoordinatorOps", "Notary", "ApostilleClerk", "Viewer"]
COORD = ["CoordinatorOps"]
NOTARY = ["Notary"]
CLERK = ["ApostilleClerk"]
