"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priority 1-2).

Headers (PRD §2.1):
  X-User-ID   : the acting principal id
  X-User-Role : one of {PlatformAdmin, LocationManager, Member, Technician}

Auth (priority 1): both X-User-ID and X-User-Role must be present and X-User-Role
                   must be a recognized role, else ERR_UNAUTHENTICATED (401).
RBAC (priority 2): the role must be permitted for the operation, else
                   ERR_FORBIDDEN (403). Ownership checks for entity-backed roles
                   are applied per-endpoint after existence resolution.
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"PlatformAdmin", "LocationManager", "Member", "Technician"}


def authenticate():
    """Validate the auth headers; populate g.user_role / g.user_id. Raises on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated()
    if user_id is None or user_id == "":
        raise errors.unauthenticated()
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    """Decorator: authenticate first, then enforce RBAC against the allowed roles."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
