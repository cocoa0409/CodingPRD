"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request, g

import constants as C
from errors import err


def authenticate():
    """Populate g.user_id / g.role; raise ERR_UNAUTHENTICATED on bad headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in C.ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Role gate (ERR_FORBIDDEN). Auth must have run first."""
    if g.role not in roles:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")


def is_customer():
    return g.role == "Customer"
