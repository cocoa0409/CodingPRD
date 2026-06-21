"""Auth header extraction and RBAC enforcement.

PRD 2.1: two mandatory headers, X-User-ID and X-User-Role.
Roles: Traveler, Approver, FinanceAdmin (spelled exactly).
Missing header or unknown role -> ERR_UNAUTHENTICATED (401).
Valid request whose role lacks permission -> ERR_UNAUTHORIZED (403).
"""
from functools import wraps

from flask import request, g

from errors import err

KNOWN_ROLES = {"Traveler", "Approver", "FinanceAdmin"}


def authenticate():
    """Validate the two auth headers and stash identity on flask.g.

    Raises ERR_UNAUTHENTICATED if either header is missing/blank or the role
    is outside the known set.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if user_role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown X-User-Role")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce that the acting role is allowed.

    Order matters (PRD 2.6): auth (401) before authorization (403).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed_roles:
                raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
