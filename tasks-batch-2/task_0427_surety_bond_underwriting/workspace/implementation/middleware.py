"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priority 1-2).

Headers (PRD §2.1):
  X-User-ID   : opaque acting-operator identifier (NOT tied to any entity)
  X-User-Role : one of {Underwriter, SeniorUnderwriter, ClaimsExaminer}

Auth (priority 1): X-User-Role must be present and a recognized role else
                   ERR_UNAUTHENTICATED (401).
RBAC (priority 2): role must be permitted for the operation else ERR_FORBIDDEN (403).

X-User-ID is never compared to any stored foreign key; authorization is governed
entirely by X-User-Role plus the operation.
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"Underwriter", "SeniorUnderwriter", "ClaimsExaminer"}


def authenticate():
    """Validate X-User-Role; populate g.user_role / g.user_id. Raises on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
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
