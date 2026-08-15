"""Auth header extraction and role checking."""

from functools import wraps

from flask import request

import errors

ALL_ROLES = {
    "PlatformAdmin",
    "ProgramManager",
    "Designer",
    "ComplianceOfficer",
    "ProductionPlanner",
    "WarehouseOperator",
    "LogisticsCoordinator",
    "ClaimsAdjuster",
    "FieldServiceManager",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise errors.err_unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Decorator: authenticate, then check the role is in the allowed set."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = get_auth()
            if role not in roles:
                raise errors.err_unauthorized()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
