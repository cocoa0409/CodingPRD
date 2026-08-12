"""Auth header extraction and role checking (PRD §2.1, gates 1-2 of §2.8)."""

import functools

from flask import request

from errors import ApiError, ERR_MISSING_HEADERS, ERR_UNAUTHORIZED_ROLE

ROLES = {
    "Customer",
    "Assessor",
    "ProjectManager",
    "RebuildEngineer",
    "QualityInspector",
    "Trainer",
    "LogisticsCoordinator",
    "WarrantyAdministrator",
    "PlatformAdmin",
}


def caller():
    """Extract and validate X-User-ID / X-User-Role (validation gate 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_HEADERS,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role name",
            401,
        )
    return user_id, role


def require_roles(*allowed):
    """Decorator: gate 1 (headers) then gate 2 (role permitted for endpoint)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = caller()
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED_ROLE,
                    f"role {role} is not permitted for this endpoint",
                    403,
                )
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator


def forbidden(message="ownership check failed"):
    return ApiError(ERR_UNAUTHORIZED_ROLE, message, 403)
