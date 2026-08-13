"""Auth context extraction and role checking per PRD section 2.1."""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = [
    "SystemAdmin",
    "AthleticTrainer",
    "AthleticDirector",
    "SchoolNurse",
    "Physician",
    "TeamCoach",
    "ParentGuardian",
]


def get_ctx():
    """Validate X-User-ID / X-User-Role headers (validation priority 1)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be recognized.",
        )
    return {"uid": uid, "role": role}


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ctx = get_ctx()
            if ctx["role"] not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE",
                    "The caller's role is not authorized for this endpoint.",
                )
            return fn(ctx, *args, **kwargs)

        return wrapper

    return decorator
