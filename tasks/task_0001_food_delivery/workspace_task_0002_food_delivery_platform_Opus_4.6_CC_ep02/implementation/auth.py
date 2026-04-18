from functools import wraps
from flask import request
from errors import APIError

VALID_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}

ENDPOINT_ROLES = {}


def require_roles(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")

            if not user_id or not user_role or user_role not in VALID_ROLES:
                raise APIError("ERR_AUTH_REQUIRED", "Authentication required")

            if user_role not in roles:
                raise APIError("ERR_FORBIDDEN", "Role not authorized for this endpoint")

            request.user_id = user_id
            request.user_role = user_role
            return f(*args, **kwargs)
        return wrapper
    return decorator


def check_ownership(resource_owner_id, user_id, user_role, owner_roles):
    if user_role in owner_roles and resource_owner_id != user_id:
        raise APIError("ERR_FORBIDDEN", "Access denied: identity mismatch")
