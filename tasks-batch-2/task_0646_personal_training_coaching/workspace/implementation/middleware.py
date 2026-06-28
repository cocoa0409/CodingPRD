"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priority 1-2).

Headers:
  X-User-ID   : acting user identifier
  X-User-Role : one of {PlatformAdmin, Trainer, Client}

Auth (priority 1):  both X-User-ID and X-User-Role present and well-formed, and
                    X-User-Role a recognized role, else ERR_MISSING_AUTH (401).
RBAC (priority 2):  role permitted for the operation, else ERR_FORBIDDEN_ROLE (403).
                    Ownership (entity_backed) checks live in the service layer
                    because they need the resolved resource.
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"PlatformAdmin", "Trainer", "Client"}


def authenticate():
    """Validate X-User-ID / X-User-Role; populate g.user_role / g.user_id.

    Both headers must be present and non-empty, and X-User-Role must be one of
    the three recognized roles, else ERR_MISSING_AUTH.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not isinstance(role, str) or role not in VALID_ROLES:
        raise errors.missing_auth()
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.missing_auth()
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    """Decorator: authenticate first, then enforce RBAC against the allowed roles."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden_role()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
