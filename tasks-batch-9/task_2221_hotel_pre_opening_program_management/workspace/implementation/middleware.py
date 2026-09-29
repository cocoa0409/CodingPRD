"""Authentication + RBAC (PRD §2.1, validation tiers 1-2)."""
from functools import wraps

from flask import request, g

from errors import ApiError

ROLES = (
    "ProgramDirector",
    "ConstructionManager",
    "LicensingCoordinator",
    "SystemsIntegrator",
    "TalentManager",
    "ProcurementManager",
    "CommercialDirector",
    "QualityInspector",
)
ALL_ROLES = ROLES


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "A valid X-User-Role header is required.")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require(*roles):
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s may not perform this operation." % g.user_role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id
