"""Authentication and role authorization (PRD 2.1, 2.8 steps 1-2)."""
from flask import request

import config
from errors import raise_error


def authenticate():
    """Step 1: both headers present and the role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error("ERR_UNAUTHENTICATED")
    if role not in config.ALL_ROLES:
        raise_error("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(allowed_roles):
    """Step 2 (role membership). Ownership is checked once the target loads."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise_error("ERR_UNAUTHORIZED")
    return user_id, role


def deny_unauthorized():
    raise_error("ERR_UNAUTHORIZED")
