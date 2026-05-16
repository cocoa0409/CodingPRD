"""Auth header parsing and RBAC decorator.

Per PRD §2.1: every request carries X-User-ID and X-User-Role
(except GET /_clock).
"""

from functools import wraps
from flask import request, g
from core.errors import raise_error


VALID_ROLES = {"ComplianceOfficer", "Coach", "Athlete", "Booster", "Auditor"}


def parse_auth():
    """Validate auth headers; populate g.user_id and g.user_role.

    Skips auth entirely for GET /_clock (PRD §2.1). The clock-advance endpoint
    still requires both headers.
    """
    # Auth-exempt: only GET /_clock; everything else (including POST /_clock/advance)
    # requires headers.
    if request.method == "GET" and request.path == "/_clock":
        g.user_id = None
        g.user_role = None
        return

    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_error("ERR_AUTH_MISSING", "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise_error("ERR_AUTH_INVALID_ROLE", f"X-User-Role '{user_role}' is invalid")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles):
    """Decorator: only the listed roles may invoke the endpoint."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.user_role not in roles:
                raise_error("ERR_FORBIDDEN", f"Role {g.user_role} is not permitted")
            return fn(*args, **kwargs)
        return wrapped
    return decorator
