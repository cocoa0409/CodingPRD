"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.9)."""
from functools import wraps

from flask import request, g

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"CFO", "Bookkeeper", "ClientContact", "PlatformAdmin"}


def authenticate():
    """Validate the two mandatory headers. Sets g.user_id / g.role.

    Raises ERR_UNAUTHENTICATED if either header is missing or the role is
    not one of the four recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce the RBAC role list for the route.

    Order matches PRD §2.9: auth (401) before role authorization (403).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise err(ERR_FORBIDDEN_ROLE,
                          "Role %s is not permitted to perform this operation." % g.role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
