"""Auth header extraction and role checking (PRD 2.1, ladder levels 1-3)."""

import functools

from flask import g, request

from constants import ALL_ROLES, ROLE_TENANT_REP
from errors import ApiError


def endpoint(roles, needs_user_id=False):
    """Level 1 authentication, then level 2 authorisation, then level 3 identity."""

    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role is None or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")
            user_id = request.headers.get("X-User-ID")
            if user_id is not None and user_id == "":
                user_id = None
            if needs_user_id and user_id is None:
                raise ApiError("ERR_MISSING_USER_ID")
            g.role = role
            g.user_id = user_id
            return view(*args, **kwargs)

        return wrapped

    return decorator


def is_tenant_caller():
    return getattr(g, "role", None) == ROLE_TENANT_REP


def caller_tenant_id():
    return getattr(g, "user_id", None)
