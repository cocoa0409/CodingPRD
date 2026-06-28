"""Auth header extraction and RBAC (PRD §2.1, scaffold §1.4 / §1.7).

Headers (PRD §2.1): X-User-ID identifies the acting principal; X-User-Role
names their operational capacity. Recognized roles: StudioManager, Member,
Instructor, Anonymous.
"""
from flask import request

from constants import VALID_ROLES
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE


def get_auth():
    """Return (user_id, role) from the request headers, or (None, None)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth():
    """Validation priority 1 (auth). Both headers present and well-formed; role
    must be one of the four recognized values. Returns (user_id, role)."""
    user_id, role = get_auth()
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2 (auth). Acting role must be permitted."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)
