"""Authentication and RBAC middleware. Roles come from PRD §2.1."""
from functools import wraps

from flask import request

from .errors import raise_error


VALID_ROLES = {"Customer", "Driver", "Dispatcher", "SortingHubOperator", "ComplianceOfficer"}


def _headers():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or not isinstance(user_id, str) or not isinstance(user_role, str):
        raise_error("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    user_role = user_role.strip()
    if not user_id or not user_role:
        raise_error("ERR_UNAUTHENTICATED")
    if user_role not in VALID_ROLES:
        # The role string isn't even one we recognize -> not allowed for any endpoint.
        raise_error("ERR_FORBIDDEN")
    return user_id, user_role


def authed(allowed_roles):
    """Decorator: require auth headers and role membership in `allowed_roles`."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = _headers()
            if user_role not in allowed:
                raise_error("ERR_FORBIDDEN")
            return fn(user_id, user_role, *args, **kwargs)
        return wrapper
    return decorator


def current_identity():
    return _headers()
