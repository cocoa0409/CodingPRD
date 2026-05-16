"""Authentication and role-based access control. PRD §2.1 / SCAFFOLD §1.7.

All endpoints (except the test reset path and /_clock/advance auth itself) require:
- X-User-ID header (non-empty)
- X-User-Role header (must be one of the four valid roles)

The Parent role is entity-backed: X-User-ID is the id of an existing ParentAccount.
The other three roles (DistrictReviewer, CafeteriaManager, AuditOfficer) are opaque.
"""

from functools import wraps
from flask import request, g

from core.errors import raise_error


VALID_ROLES = {"Parent", "DistrictReviewer", "CafeteriaManager", "AuditOfficer"}


def parse_auth():
    """Read X-User-ID and X-User-Role from request; set g.user_id and g.user_role.

    Raises ERR_UNAUTHENTICATED if missing/empty. We treat an unknown role string
    the same as missing — it produces ERR_UNAUTHENTICATED (SCAFFOLD priority 1).
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_error("ERR_UNAUTHENTICATED",
                    "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise_error("ERR_UNAUTHENTICATED",
                    f"X-User-Role '{user_role}' is invalid")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles):
    """Decorator restricting an endpoint to the listed roles. Returns ERR_FORBIDDEN."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.user_role not in roles:
                raise_error("ERR_FORBIDDEN",
                            f"Role {g.user_role} is not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapped
    return decorator
