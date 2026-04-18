from functools import wraps
from flask import request, g
from utils.response import err

VALID_ROLES = {'Customer', 'Restaurant', 'Rider', 'CustomerService', 'PlatformAdmin'}


def require_auth(allowed_roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get('X-User-ID')
            user_role = request.headers.get('X-User-Role')
            if not user_id or not user_role or user_role not in VALID_ROLES:
                return err('ERR_AUTH_REQUIRED', 'Missing or invalid authentication headers.')
            if user_role not in allowed_roles:
                return err('ERR_FORBIDDEN', 'Role not authorized for this endpoint.')
            g.user_id = user_id
            g.user_role = user_role
            return f(*args, **kwargs)
        return wrapper
    return decorator
