"""Auth middleware — PRD §2.1, headers X-User-ID and X-User-Role."""
from functools import wraps

from flask import g, request

from .errors import APIError


VALID_ROLES = {"FamilyUser", "DistrictAdmin", "SystemOperator"}


def _extract_headers():
    # PRD §2.1: a header is "absent" only when not present in the request.
    # A present-but-empty X-User-Role is still a value outside the recognized
    # set and therefore yields ERR_AUTH_INVALID_ROLE per §2.1.
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if user_id is None or user_role is None:
        raise APIError("ERR_AUTH_MISSING", "X-User-ID and X-User-Role headers are required")
    if not user_id:
        # Empty X-User-ID has no analogous PRD "value" clause; treat as missing.
        raise APIError("ERR_AUTH_MISSING", "X-User-ID is required")
    if user_role not in VALID_ROLES:
        raise APIError("ERR_AUTH_INVALID_ROLE", f"Unknown role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role


def require_auth(*allowed_roles):
    """Decorator that enforces:
      1) presence of auth headers (ERR_AUTH_MISSING),
      2) recognized role (ERR_AUTH_INVALID_ROLE),
      3) role is in allowed_roles for this endpoint (ERR_FORBIDDEN).
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _extract_headers()
            if allowed_roles and g.user_role not in allowed_roles:
                raise APIError("ERR_FORBIDDEN", f"Role {g.user_role} not permitted on this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
