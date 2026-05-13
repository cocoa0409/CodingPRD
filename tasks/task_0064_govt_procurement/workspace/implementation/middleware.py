"""Auth header extraction and role checking.

Per PRD §2.1 every request must carry X-User-ID and X-User-Role (both non-empty).
The four valid roles are exactly: ProcurementOfficer, Supplier, EvaluationExpert,
Regulator.
"""

from functools import wraps

from flask import g, request

from errors import (
    ERR_AUTH_INVALID_ROLE,
    ERR_AUTH_MISSING,
    ERR_FORBIDDEN,
    raise_error,
)


VALID_ROLES = {"ProcurementOfficer", "Supplier", "EvaluationExpert", "Regulator"}


def require_auth():
    """Validate X-User-ID / X-User-Role headers and populate g.user_id / g.user_role."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        raise_error(ERR_AUTH_MISSING, "X-User-ID and X-User-Role headers required")
    if role not in VALID_ROLES:
        raise_error(ERR_AUTH_INVALID_ROLE, f"unknown role: {role}")
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles):
    """Decorator factory: require the caller's role to be in allowed_roles."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = getattr(g, "user_role", None)
            if role is None or role not in VALID_ROLES:
                raise_error(ERR_FORBIDDEN, "role not permitted")
            if role not in allowed_roles:
                raise_error(ERR_FORBIDDEN, f"role {role} not permitted on this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco
