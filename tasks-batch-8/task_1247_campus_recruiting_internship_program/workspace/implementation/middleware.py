"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC."""

from functools import wraps
from flask import request, g

from errors import err_unauthenticated, err_forbidden

ROLES = {"RecruitingAdmin", "Recruiter", "Candidate", "Evaluator", "Mentor", "Anonymous"}


def require_auth(allowed_roles):
    """Decorator: checks auth headers and role authorization."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise err_unauthenticated()
            if role not in allowed_roles:
                raise err_forbidden()
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
