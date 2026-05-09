from functools import wraps
from flask import request, g

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)


VALID_ROLES = {"SurgicalCoordinator", "DepartmentHead", "Scheduler", "BillingAdmin", "Any"}


def auth_required(*allowed_roles):
    """Validate auth headers and (optionally) role membership.

    `allowed_roles` is the set of roles permitted on this endpoint. The literal
    `Any` token in the allowed list means any authenticated role is fine.
    """
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID", "").strip()
            user_role = request.headers.get("X-User-Role", "").strip()
            if not user_id or not user_role:
                raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                            "X-User-ID and X-User-Role headers must be present and non-empty")

            g.user_id = user_id
            g.user_role = user_role

            if "Any" in allowed:
                return fn(*args, **kwargs)
            if user_role not in allowed:
                raise_error(ERR_INSUFFICIENT_PERMISSIONS,
                            f"Role {user_role} lacks permission for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return deco
