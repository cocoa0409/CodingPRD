"""Auth header extraction and role/RBAC checking."""
from functools import wraps

from flask import g, request

from errors import (
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    err,
)


VALID_ROLES = {"Volunteer", "Organizer", "SkillAdmin"}


def auth_required(allowed_roles):
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in VALID_ROLES:
                raise err(ERR_UNAUTHENTICATED, "missing or invalid auth headers")
            if user_role not in allowed:
                raise err(ERR_FORBIDDEN, f"role {user_role} not authorized for endpoint")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def get_user():
    return g.user_id, g.user_role
