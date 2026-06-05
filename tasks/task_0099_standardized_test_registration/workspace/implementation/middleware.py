"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD validations 1-2).

Auth headers: X-User-ID, X-User-Role.
Roles: Candidate, TestCenterAdmin, AccommodationReviewer, ScoreOps.
"""
import functools

from flask import request, g

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

KNOWN_ROLES = {"Candidate", "TestCenterAdmin", "AccommodationReviewer", "ScoreOps"}


def authenticate():
    """Validate auth headers. Returns (user_id, role) or raises ApiError(401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: authenticate then check role is permitted for this operation.

    Validation order per PRD §2.6: ERR_UNAUTHENTICATED (401) before
    ERR_UNAUTHORIZED (403), both before any existence/business checks.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
