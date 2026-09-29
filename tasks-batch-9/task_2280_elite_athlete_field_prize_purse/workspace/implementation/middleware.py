"""Authentication (priority 1) and endpoint role permission (priority 2)."""
from flask import g, request

from constants import ROLES
from errors import err


def authenticate(allowed_roles):
    """Priority 1 then priority 2, in that order (PRD 2.11)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required")
    if role not in allowed_roles:
        raise err("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint" % role)
    g.user_role = role
    g.user_id = user_id
    return role, user_id
