"""Auth header extraction and role checks (PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"StudioAdmin", "Instructor", "Member"}


class Principal(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Extract and validate the two mandatory auth headers.

    Raises ERR_UNAUTHENTICATED (priority 1) when missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown role value")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Priority 2: ERR_FORBIDDEN_ROLE when the role is not permitted for the endpoint."""
    if principal.role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % principal.role)
