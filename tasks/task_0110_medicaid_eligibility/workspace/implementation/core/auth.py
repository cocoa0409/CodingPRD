"""Auth header parsing and RBAC decorator (PRD §2.1).

Headers: X-User-ID, X-User-Role
Roles: IntakeWorker, EligibilityCaseworker, AppealsOfficer, PolicyAdmin
"""

from functools import wraps
from flask import request, g

from core.errors import raise_error


VALID_ROLES = {"IntakeWorker", "EligibilityCaseworker", "AppealsOfficer", "PolicyAdmin"}


def parse_auth():
    """Read X-User-ID/X-User-Role; raise ERR_UNAUTHENTICATED on bad/missing."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_error("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise_error("ERR_UNAUTHENTICATED", f"X-User-Role '{user_role}' is invalid")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles):
    """Decorator restricting endpoint to the listed roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.user_role not in roles:
                raise_error("ERR_FORBIDDEN", f"Role {g.user_role} is not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapped
    return decorator
