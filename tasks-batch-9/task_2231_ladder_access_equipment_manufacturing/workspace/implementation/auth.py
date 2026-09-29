"""Header authentication and role authorization (PRD 2.1, ladder steps 1-2)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "DesignEngineer",
    "DesignApprover",
    "TestLabTechnician",
    "ProductionSupervisor",
    "ComplianceOfficer",
    "CertificationBody",
    "Consumer",
    "SafetyDirector",
    "SystemOperator",
)


def authorize(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "X-User-ID and a recognized X-User-Role header are required",
                )
            if role not in allowed_roles:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "role %s may not call this operation" % role,
                )
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator
