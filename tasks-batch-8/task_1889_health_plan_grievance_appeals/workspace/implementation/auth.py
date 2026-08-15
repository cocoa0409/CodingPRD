"""Authentication / authorization middleware (PRD sections 2.1, 2.8)."""

from functools import wraps

from flask import request

import db
import errors


def get_identity():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str):
        raise errors.unauthenticated()
    if not role or role not in db.ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(allowed):
    """Decorator enforcing priority 1 (auth) then priority 2 (role) checks."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                raise errors.unauthorized()
            return fn(*args, _user_id=user_id, _role=role, **kwargs)
        return wrapper
    return decorator
