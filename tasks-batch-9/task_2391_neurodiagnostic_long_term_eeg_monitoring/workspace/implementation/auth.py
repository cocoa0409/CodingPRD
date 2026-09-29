"""Ladder rungs 1 and 2: authentication and role authority (PRD 2.1)."""
from flask import request

import config
from errors import ApiError


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in config.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed_roles):
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
