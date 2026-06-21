"""Auth header extraction and RBAC helpers (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"PlatformAdmin", "Dispatcher", "Customer", "Groomer"}


def get_identity():
    """Extract and validate X-User-ID / X-User-Role.

    Raises ERR_UNAUTHENTICATED (401) when either header is missing or malformed.
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err(ERR_UNAUTHENTICATED, "Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unknown role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN (403) when the acting role is not in the allowed set."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role %s may not perform this operation" % role)
