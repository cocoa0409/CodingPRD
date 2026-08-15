"""Auth header extraction and role checking per PRD section 2.1."""

from flask import request

import errors


ROLES = ("Inspector", "Veterinarian", "FeedMillOperator", "Producer")


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED when role header
    is missing/malformed/not one of the four declared roles."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise errors.unauthenticated()
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def require_roles(*allowed):
    """Check authn + authz. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.unauthorized()
    return user_id, role
