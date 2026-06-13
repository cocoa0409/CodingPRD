"""Auth header extraction and RBAC (PRD §2.1).

Two mandatory headers:
  X-User-ID   — the acting user id
  X-User-Role — one of Officer, SupervisingJudge, CompactAdministrator

Missing/empty either -> ERR_UNAUTHENTICATED (401).
Role not permitted for the operation -> ERR_UNAUTHORIZED (403).
"""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"Officer", "SupervisingJudge", "CompactAdministrator"}


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(*ERR_UNAUTHENTICATED, "Missing or empty authentication headers.")
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed):
    """Decorator: authenticate, then authorize against the allowed role set.

    Authentication (401) is always checked before authorization (403), per the
    validation priority order in PRD §2.11.
    """
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.user_role not in allowed_set:
                raise ApiError(
                    *ERR_UNAUTHORIZED,
                    "Role is not permitted to invoke this operation.",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
