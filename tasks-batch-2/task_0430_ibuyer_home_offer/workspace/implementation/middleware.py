"""Auth header extraction and RBAC checks (PRD §2.1, §4 / SCAFFOLD §1.4, §1.7)."""

from flask import request

from constants import ROLES
from errors import err


def authenticate():
    """Validate X-User-ID and X-User-Role headers are present and well-formed.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) on missing /
    malformed headers. A well-formed role is one of the three declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if user_id.strip() == "" or role.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Empty X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not in the allowed set for this endpoint."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
