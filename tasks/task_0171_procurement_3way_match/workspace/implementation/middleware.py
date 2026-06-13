"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.6)."""
from functools import wraps
from flask import request, g

import errors
from errors import ApiError

VALID_ROLES = {
    "ProcurementAdmin",
    "Buyer",
    "Approver",
    "Receiver",
    "Matcher",
    "PayablesClerk",
}


def extract_user_context():
    """Validate that both auth headers are present and well-formed.

    Returns (user_id, role). Raises ERR_MISSING_USER_CONTEXT (401) when either
    header is missing/blank, or the role is not one of the six valid roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(errors.ERR_MISSING_USER_CONTEXT, 401,
                       "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError(errors.ERR_MISSING_USER_CONTEXT, 401,
                       "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise ApiError(errors.ERR_MISSING_USER_CONTEXT, 401,
                       "Malformed or unknown X-User-Role header")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: enforce user-context (401) then role authorization (403)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_user_context()
            g.user_id = user_id
            g.user_role = role
            if role not in allowed_roles:
                raise ApiError(errors.ERR_FORBIDDEN_FOR_ROLE, 403,
                               "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# Read access: all six roles may issue GET across the resource surface.
ALL_ROLES = (
    "ProcurementAdmin",
    "Buyer",
    "Approver",
    "Receiver",
    "Matcher",
    "PayablesClerk",
)
