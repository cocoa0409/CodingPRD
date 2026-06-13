"""Auth header extraction and role checking (PRD §2.1, §2.10)."""
from functools import wraps

from flask import request, g

import errors

VALID_ROLES = {"CarrierAdmin", "Underwriter", "ClaimsAdjuster", "Traveler", "System", "Any"}
# Roles a client may legitimately declare. "Any" is a permission wildcard used in
# the endpoint matrix, not a role a client supplies; "System" denotes server
# automation. The PRD lists all six as recognized roles, so we accept any of them
# as a well-formed X-User-Role value (auth = present + well-formed).


def extract_auth():
    """Validate the two mandatory auth headers. Returns (user_id, role).

    Raises ERR_MISSING_AUTH (401) if either is missing/malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise errors.missing_auth()
    if not role or role not in VALID_ROLES:
        raise errors.missing_auth()
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that the caller's role is allowed.

    `Any` in the allowed set means any authenticated role passes.
    Auth (401) is always checked before authorization (403).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_auth()
            if "Any" not in allowed and role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return decorator
