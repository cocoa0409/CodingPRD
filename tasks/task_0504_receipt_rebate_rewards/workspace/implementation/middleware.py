"""Auth header extraction and RBAC (PRD §2.1, §2.11).

Validation priority order (PRD §2.11):
  1. auth: X-User-Role present + recognized      -> ERR_UNAUTHENTICATED (401)
  2. authz: role permitted for the operation     -> ERR_FORBIDDEN (403)
Existence / shape / state / business checks happen after these in the routes.
"""
from flask import request

from constants import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import err


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if the role header is
    missing or not a recognized role."""
    role = request.headers.get(HEADER_USER_ROLE)
    user_id = request.headers.get(HEADER_USER_ID)
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN if `role` is not in the allowed set/list."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role '%s' is not permitted for this operation." % role)
