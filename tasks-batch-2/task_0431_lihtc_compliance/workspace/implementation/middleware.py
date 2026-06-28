"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.4, §1.7)."""

from flask import g, request

import errors

VALID_ROLES = {"OwnerAgent", "StateHFA"}


def authenticate():
    """Validate the two mandatory auth headers. Raises ApiError on failure.

    Universal: every request (including /_clock/set_current_utc) requires both
    headers. Stores the acting identity on flask.g for downstream handlers.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise errors.unauthenticated()
    if not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    g.user_id = user_id
    g.role = role


def require_role(*allowed_roles):
    """Authorization check: the acting role must be in allowed_roles."""
    if g.get("role") not in allowed_roles:
        raise errors.unauthorized()
