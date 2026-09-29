"""Header-based authentication and role authorization (ladder steps 1-2)."""

from flask import request

import constants as K
from errors import ApiError


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")

    if role not in K.ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    return user_id, role
