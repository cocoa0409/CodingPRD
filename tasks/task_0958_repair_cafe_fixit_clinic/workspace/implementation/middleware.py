"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1-2)."""

from functools import wraps

from flask import g, request

from errors import (
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    raise_err,
)

ROLES = {"Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer"}


def authenticate():
    """Priority 1: X-User-Role and X-User-ID present, role is declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role / X-User-ID headers")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Priority 2: the caller's role must be permitted for the endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in roles:
                raise_err(
                    ERR_UNAUTHORIZED_ROLE,
                    "Role %s is not permitted for this operation" % g.role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
