"""Auth header extraction and RBAC helpers (PRD §2.1, §3.10)."""
from flask import request

from constants import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import err


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_manager(self):
        return self.role == "StudioManager"

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_instructor(self):
        return self.role == "Instructor"


def authenticate():
    """Validate the two mandatory auth headers. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    if not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    return Principal(user_id.strip(), role)


def require_roles(principal, allowed_roles):
    """Authorize the principal's role against the endpoint's allowed roles."""
    if principal.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
