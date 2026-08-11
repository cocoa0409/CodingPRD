"""Auth header extraction and role-based access control (PRD section 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "OrchardManager",
    "CellarLead",
    "ComplianceOfficer",
    "PackagingOperator",
    "SalesRep",
    "PlatformAdmin",
}


def require_roles(*allowed):
    """401 when headers are missing/malformed; 403 when the role is not
    permitted for the endpoint. Auth (401) always precedes RBAC (403)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if not role or role not in ROLES or not user_id:
                raise ApiError(
                    ERR_UNAUTHENTICATED,
                    "Missing or malformed X-User-Role / X-User-ID",
                    401,
                )
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED,
                    f"Role {role} not permitted for this endpoint",
                    403,
                )
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return decorator
