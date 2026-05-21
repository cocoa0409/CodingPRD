"""Authentication and RBAC enforcement."""

from functools import wraps
from flask import request, g

from common import ApiError


VALID_ROLES = {"Caseworker", "HouseholdHead", "Merchant", "FraudInvestigator", "StateAdministrator", "SystemTest"}


def require_auth(allowed_roles):
    """Decorator: enforces header presence and role authorization."""
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role:
                raise ApiError("ERR_AUTH_MISSING", 401, "X-User-ID and X-User-Role required")
            if user_role not in VALID_ROLES:
                raise ApiError("ERR_FORBIDDEN", 403, "Unknown role")
            if user_role not in allowed_set:
                raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
