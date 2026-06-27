"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priority 1-2).

Headers (PRD §2.1):
  X-User-ID   : acting principal identifier
  X-User-Role : one of {PlatformAdmin, Customer, StoreAssociate, ServiceTech, PriceAdmin}

Auth (priority 1): both X-User-ID and X-User-Role must be present and the role
                   recognized, else ERR_UNAUTHENTICATED (401).
RBAC (priority 2): the acting role must be permitted for the operation, else
                   ERR_FORBIDDEN_ROLE (403).
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"PlatformAdmin", "Customer", "StoreAssociate", "ServiceTech", "PriceAdmin"}


def authenticate():
    """Validate X-User-ID + X-User-Role; populate g.user_role / g.user_id.

    A request missing either header, or carrying an unrecognized role, is
    rejected with ERR_UNAUTHENTICATED (PRD §2.1).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role not in VALID_ROLES:
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
