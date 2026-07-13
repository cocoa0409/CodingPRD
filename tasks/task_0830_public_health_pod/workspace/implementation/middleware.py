"""Auth + RBAC middleware (PRD 2.1, SCAFFOLD.yaml validations priority 1-2)."""
import functools

from flask import g, request

from errors import ApiError

VALID_ROLES = {
    "PublicHealthAdmin",
    "LogisticsCoordinator",
    "MutualAidPartner",
    "ClinicalLead",
    "Volunteer",
}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers.", 401)
    g.user_id = user_id
    g.user_role = user_role


def require_role(*allowed_roles):
    """Decorator: priority-1 auth check, then priority-2 role check."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise ApiError("ERR_FORBIDDEN", f"Role {g.user_role} may not call this endpoint.", 403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
