"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import err_unauthenticated, err_unauthorized

ROLES = {"CastingDirector", "CastingAssociate", "Agent", "ProductionCoordinator", "Guardian"}


def get_actor():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err_unauthenticated()
    if not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validate headers, then endpoint role permission. Returns (user_id, role)."""
    user_id, role = get_actor()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role
