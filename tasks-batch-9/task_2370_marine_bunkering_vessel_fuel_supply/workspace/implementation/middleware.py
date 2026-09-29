"""Authentication and role authorisation (PRD 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "OpsCoordinator",
    "ComplianceOfficer",
    "Surveyor",
    "CreditController",
    "LabTechnician",
    "CustomerRep",
    "BargeMaster",
)


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    g.user_id = user_id
    g.role = role


def roles(*allowed_roles):
    """Decorator enforcing validation steps 1 and 2 of PRD 2.8."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
