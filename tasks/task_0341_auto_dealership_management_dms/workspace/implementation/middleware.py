"""Auth (X-User-ID / X-User-Role) extraction + RBAC enforcement.

Header names and role values are taken from PRD §2.1.
"""
from functools import wraps

from flask import request

from errors import err

RECOGNIZED_ROLES = {
    "InventoryClerk",
    "SalesManager",
    "FinanceManager",
    "ServiceAdvisor",
    "TitleClerk",
    "Customer",
}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def authenticate():
    """Validation priority 1: X-User-Role present and recognized => else ERR_UNAUTHENTICATED."""
    role = get_role()
    if not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role header missing or unrecognized")
    return role


def require_roles(*allowed):
    """Validation priority 2: role permitted for this operation => else ERR_FORBIDDEN.

    Authentication runs first (priority 1), then authorization (priority 2).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = authenticate()
            if role not in allowed:
                raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
