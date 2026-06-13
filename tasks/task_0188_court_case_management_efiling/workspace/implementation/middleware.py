"""Auth header extraction and RBAC (PRD 2.1)."""
from flask import request

import errors

VALID_ROLES = {"Clerk", "Judge", "Attorney", "SystemAdmin"}


def get_actor():
    """Validate the two mandatory auth headers; return (user_id, role).

    Raises ERR_UNAUTHENTICATED if either header is missing or the role is not
    one of the four permitted values.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Enforce that the acting role is in the allowed set (RBAC matrix)."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
