"""Auth header extraction and RBAC (PRD §2.1, §3.9 precedence).

Every request carries X-User-ID and X-User-Role. Missing either ->
ERR_UNAUTHENTICATED (401). Role not permitted for the op -> ERR_FORBIDDEN_ROLE
(403). Validation precedence (PRD §3.9): auth (401) before role (403) before
existence (404) before ownership (403) before state, OCC, business checks.
"""

from functools import wraps

from flask import request, g

import errors
from errors import err

VALID_ROLES = {"ShopStaff", "ProductionOperator", "Customer"}


def authenticate():
    """Resolve identity from headers. Raises ERR_UNAUTHENTICATED on absence."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator enforcing auth (401) then role membership (403), in that order."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, user_role = authenticate()
            if user_role not in allowed:
                raise err(
                    errors.ERR_FORBIDDEN_ROLE,
                    "Role %s is not permitted for this operation" % user_role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
