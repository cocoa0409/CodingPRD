from functools import wraps
from flask import request
from errors import raise_error, ERR_AUTH_REQUIRED, ERR_FORBIDDEN

VALID_ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def get_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise_error(ERR_AUTH_REQUIRED, "Missing or invalid authentication headers.")
    return user_id, user_role


def require_roles(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_auth()
            if user_role not in allowed_roles:
                raise_error(ERR_FORBIDDEN, f"Role '{user_role}' is not authorized for this endpoint.")
            request.user_id = user_id
            request.user_role = user_role
            return f(*args, **kwargs)
        return wrapper
    return decorator
