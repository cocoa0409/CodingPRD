"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1-2).

Headers (PRD §2.1):
  X-User-ID   : identifies the acting principal. For Agency it is the acting
                Agency entity id (entity-backed ownership). For TitleOfficer and
                Underwriter it is an opaque operator id never matched to any entity.
  X-User-Role : exactly one of {Agency, TitleOfficer, Underwriter}.

Auth (priority 1): both X-User-ID and X-User-Role must be present, and
                   X-User-Role must be a recognized role, else ERR_UNAUTHENTICATED (401).
RBAC (priority 2): the role must be permitted for the operation else
                   ERR_UNAUTHORIZED (403). Agency ownership (Order.agency_id ==
                   X-User-ID) is enforced separately in the routes via
                   require_agency_owns_order(), which propagates to every resource
                   reachable through one of the agency's orders.
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"Agency", "TitleOfficer", "Underwriter"}


def authenticate():
    """Validate identity headers; populate g.user_role / g.user_id. Raises on failure."""
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
                raise errors.unauthorized()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
