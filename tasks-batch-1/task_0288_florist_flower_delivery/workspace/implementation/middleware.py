"""Auth header extraction and role checking (PRD §2.1, §2.9)."""
from flask import request

import errors

VALID_ROLES = {"Customer", "Florist", "Dispatcher", "CatalogAdmin"}


def require_auth():
    """Validate the two mandatory headers. Returns (user_id, role).
    Raises ERR_UNAUTHENTICATED when either is missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated("Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise errors.unauthenticated("Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise errors.unauthenticated("Unrecognized role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """Role-authorization check (priority 2). Raises ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise errors.forbidden_role(
            "Role %s is not permitted to call this endpoint" % role
        )
