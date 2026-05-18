from flask import request
from errors import raise_error, ERR_AUTH_REQUIRED, ERR_FORBIDDEN

VALID_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def check_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise_error(ERR_AUTH_REQUIRED, "Missing or invalid authentication headers")
    request.user_id = user_id
    request.user_role = user_role


def require_roles(*roles):
    def decorator(f):
        f._authorized_roles = set(roles)
        return f
    return decorator


def check_role_permission(authorized_roles):
    if request.user_role not in authorized_roles:
        raise_error(ERR_FORBIDDEN, f"Role {request.user_role} not authorized")
