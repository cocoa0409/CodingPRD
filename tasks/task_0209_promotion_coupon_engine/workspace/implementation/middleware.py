"""Auth header extraction and RBAC (PRD §2.1, §2.9 priorities 1-2)."""
from functools import wraps

from flask import request

from errors import err

VALID_ROLES = {"MerchantAdmin", "Shopper", "PlatformOperator"}


def get_identity():
    """Return (user_id, role) after validating auth headers.

    Raises ERR_UNAUTHENTICATED when a header is missing or the role is unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: validate auth (priority 1) then role permission (priority 2)."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
