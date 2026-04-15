"""Auth middleware: extract headers, validate role."""

from flask import request
from errors import raise_error, ERR_UNAUTHORIZED, ERR_FORBIDDEN

VALID_ROLES = {"platform_admin", "restaurant", "customer", "rider", "customer_service"}


def get_auth():
    """Return (user_id, role). Raises ApiError on failure."""
    user_id = request.headers.get("X-User-ID") or request.headers.get("X-User-Id")
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise_error(ERR_UNAUTHORIZED, "Missing or invalid X-User-Role header.")
    if not user_id:
        raise_error(ERR_UNAUTHORIZED, "Missing X-User-ID header.")
    return user_id, role


def require_roles(*allowed_roles):
    """Call get_auth and verify the role is in allowed_roles."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"Role '{role}' is not authorized for this endpoint.")
    return user_id, role
