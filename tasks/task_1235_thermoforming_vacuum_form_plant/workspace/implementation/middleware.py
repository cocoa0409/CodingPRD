"""Auth header extraction and role authorization (PRD §2.1, SCAFFOLD §1.7)."""

from functools import wraps

from flask import request

from db import LOCK
from errors import ApiError

ROLES = {
    "MaterialsPlanner",
    "ToolingEngineer",
    "PackagingEngineer",
    "PlantManager",
    "ProductionScheduler",
    "QualityInspector",
    "Any",
}

# Marker: any authenticated (recognized) role may use the endpoint.
ANY_ROLE = "*ANY*"


def current_identity():
    """Priority 1: X-User-ID and X-User-Role present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip():
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return user_id.strip(), role.strip()


def require_role(role, allowed):
    """Priority 2: role permitted on this endpoint."""
    if allowed == ANY_ROLE:
        if role not in ROLES:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Role '%s' is not recognized" % role)
        return
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", "Role '%s' is not permitted on this endpoint" % role
        )


def endpoint(allowed_roles):
    """Decorator: serialize access through the store lock, run auth (p1) then
    role authorization (p2), then call the handler with (user_id, role)."""

    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            with LOCK:
                user_id, role = current_identity()
                require_role(role, allowed_roles)
                return fn(user_id, role, *args, **kwargs)

        return inner

    return wrapper
