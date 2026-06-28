"""Auth header extraction and RBAC primitives per PRD §2.1."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

KNOWN_ROLES = {"Counselor", "Student", "PlatformAdmin"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_counselor(self):
        return self.role == "Counselor"

    @property
    def is_student(self):
        return self.role == "Student"

    @property
    def is_admin(self):
        return self.role == "PlatformAdmin"


def authenticate():
    """Validate the mandatory auth headers. Returns a Caller.
    Raises ERR_UNAUTHENTICATED when missing or role unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """ERR_FORBIDDEN when caller.role is not in the allowed set for the op."""
    if caller.role not in allowed:
        raise err(ERR_FORBIDDEN, "Role %s not permitted for this operation" % caller.role)
