"""Authentication and role authorisation (PRD 2.1, rejection ladder steps 1-2)."""
from functools import wraps

from flask import g, request

import constants
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED


def authenticate():
    user_id = request.headers.get(constants.HEADER_USER_ID)
    role = request.headers.get(constants.HEADER_USER_ROLE)
    if user_id is None or not str(user_id).strip():
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID header is missing or blank")
    if role is None or not str(role).strip():
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role header is missing or blank")
    if role not in constants.ALL_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role '%s' is not a recognised role" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*roles):
    """Decorator: step 1 authentication, then step 2 endpoint role membership."""
    allowed = tuple(roles) if roles else constants.ALL_ROLES

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED,
                    "role %s may not call this endpoint" % role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id():
    return g.get("user_id")


def current_role():
    return g.get("role")
