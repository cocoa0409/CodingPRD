"""Auth header extraction and role checking (PRD §2.1, validations priority 1-2).

Headers (PRD §2.1):
  X-User-ID   : the acting user identifier
  X-User-Role : one of {FrontDesk, Orthodontist, BillingSpecialist, Guardian,
                ClinicAdmin}

Auth (priority 1): both headers present and X-User-Role a recognized role, else
                   ERR_UNAUTHENTICATED (401).
RBAC (priority 2): role permitted for the operation, else ERR_FORBIDDEN (403).
                   Ownership checks for entity-backed roles are enforced inside
                   the route handlers (they need the resolved resource).
"""

from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {
    "FrontDesk",
    "Orthodontist",
    "BillingSpecialist",
    "Guardian",
    "ClinicAdmin",
}


def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in VALID_ROLES:
        raise errors.unauthenticated()
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    """Decorator: authenticate, then ensure the role is one of `allowed`.

    Priority 1 (auth) runs before priority 2 (RBAC); existence and everything
    else is checked inside the handler body, which runs only after both pass.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
