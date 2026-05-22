"""Auth helpers: extract user-context headers and validate role."""
from flask import request
from common import ApiError


VALID_ROLES = {"Member", "Trainer", "StoreManager", "BillingAdmin", "Any"}


def get_auth():
    """Return (user_id, role) tuple or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       f"Unrecognized role '{role}'")
    return user_id, role


def require_role(allowed_roles):
    """Raise ERR_INSUFFICIENT_PERMISSIONS if the caller's role is not in allowed_roles."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       f"Role '{role}' is not permitted for this operation")
    return user_id, role
