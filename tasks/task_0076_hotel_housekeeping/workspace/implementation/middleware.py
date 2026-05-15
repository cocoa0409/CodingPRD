"""Auth header extraction and role checking."""

from functools import wraps
from flask import request, g

from errors import (
    raise_error,
    ERR_MISSING_USER_CONTEXT,
    ERR_INSUFFICIENT_PERMISSIONS,
)


VALID_ROLES = {
    "Housekeeper",
    "Supervisor",
    "FrontDesk",
    "Engineer",
    "SystemIntegration",
}


def auth_required(allowed_roles):
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get("X-User-ID", "")
            user_role = request.headers.get("X-User-Role", "")
            if not user_id or not user_role:
                raise_error(ERR_MISSING_USER_CONTEXT,
                            "Missing or empty X-User-ID / X-User-Role headers")
            if user_role not in VALID_ROLES:
                raise_error(ERR_INSUFFICIENT_PERMISSIONS,
                            "Unknown role")
            if user_role not in allowed_set:
                raise_error(ERR_INSUFFICIENT_PERMISSIONS,
                            "Role not permitted for endpoint")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)
        return wrapped
    return deco
