"""Authentication and role authorisation (PRD sections 2.1 and 2.6 steps 1-2)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("Stakeholder", "Researcher", "ResearchLead", "PrivacyOfficer", "ResearchOpsAdmin")
ALL_ROLES = list(ROLES)


def require_roles(*allowed):
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or role is None or user_id == "" or role == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES or role not in allowed_set:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
