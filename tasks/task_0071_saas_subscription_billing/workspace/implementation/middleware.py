"""Authentication and authorization helpers."""
from functools import wraps
from flask import request, g

from errors import (
    APIError,
    raise_error,
    ERR_AUTH_MISSING_ROLE,
    ERR_AUTH_MISSING_USER,
    ERR_FORBIDDEN,
    ERR_CROSS_TENANT_ACCESS,
)


VALID_ROLES = {"PlatformAdmin", "BillingOperator", "TenantAdmin"}


def authenticate():
    """Extract X-User-Role and X-User-ID; raise auth errors per priority."""
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise_error(ERR_AUTH_MISSING_ROLE,
                    "X-User-Role header missing or not a recognized role")
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise_error(ERR_AUTH_MISSING_USER, "X-User-ID header missing")
    g.actor_role = role
    g.actor_id = user_id
    return role, user_id


def require_roles(*allowed_roles):
    """Decorator that ensures the caller's role is in allowed_roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, _ = authenticate()
            if role not in allowed_roles:
                raise_error(ERR_FORBIDDEN,
                            f"Role {role} is not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def enforce_tenant_isolation(path_tenant_id: str):
    """If caller is TenantAdmin, X-User-ID must equal path_tenant_id."""
    if g.actor_role == "TenantAdmin" and g.actor_id != path_tenant_id:
        raise_error(ERR_CROSS_TENANT_ACCESS,
                    "TenantAdmin can only access its own tenant")
