"""Auth, RBAC, request-context helpers."""
from functools import wraps
from flask import request, g
from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


VALID_ROLES = {"Admin", "IPManager", "FinanceManager", "Counsel", "InternalAgent", "ExternalAgent"}


def extract_identity():
    """Pull X-User-ID and X-User-Role from headers. Raise on missing/blank."""
    user_id = request.headers.get("X-User-ID", "").strip()
    user_role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not user_role:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*allowed_roles):
    """Decorator factory. Must be applied AFTER auth has been performed."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            extract_identity()  # priority 1
            if g.user_role not in allowed:
                raise APIError(ERR_FORBIDDEN, 403, f"Role {g.user_role} not permitted")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def current_user_id():
    return getattr(g, "user_id", None)


def current_user_role():
    return getattr(g, "user_role", None)
