"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import err, ERR_MISSING_AUTH, ERR_ROLE_FORBIDDEN

ROLES = {"PlatformAdmin", "Creator", "Backer"}


def get_identity():
    """Return (user_id, role) from headers, raising ERR_MISSING_AUTH if either absent.

    Validation priority 1: both X-User-ID and X-User-Role must be present.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(ERR_MISSING_AUTH, "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_role(allowed_roles):
    """Validate presence (priority 1) then role membership (priority 2).

    Returns (user_id, role). Raises ERR_ROLE_FORBIDDEN if role not in allowed set.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err(ERR_ROLE_FORBIDDEN, "Role '%s' is not permitted for this operation" % role)
    return user_id, role
