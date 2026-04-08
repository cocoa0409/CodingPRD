from flask import request
from errors import raise_error

VALID_ROLES = {"Customer", "Seller", "PlatformAdmin"}


def get_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise_error("ERR_AUTH_HEADER_MISSING")
    return user_id, user_role


def require_role(*roles):
    user_id, user_role = get_auth()
    if user_role not in roles:
        raise_error("ERR_FORBIDDEN")
    return user_id, user_role
