"""Authentication, role vocabulary and RBAC (PRD 2.1, ladder rules 1-3)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "PlantAdmin",
    "PlantOperator",
    "BodyEngineer",
    "BlendTechnician",
    "QualityManager",
    "ArchitectReviewer",
    "SalesRep",
    "LogisticsCoordinator",
)

ALL_ROLES = list(ROLES)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def endpoint(roles):
    """Guard an endpoint with ladder rules 1, 2 and 3, in that order."""

    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            role = request.headers.get(USER_ROLE_HEADER)
            if not user_id or not role:
                raise ApiError(
                    "ERR_MISSING_AUTH_HEADERS",
                    "Both X-User-ID and X-User-Role are required and must be non-empty.",
                )
            if role not in ROLES:
                raise ApiError("ERR_UNKNOWN_ROLE", "X-User-Role '%s' is not a known role." % role)
            if role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s is not authorised for this endpoint." % role,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


def role():
    return g.role


def is_plant_operator():
    return g.role == "PlantOperator"


def require_plant_scope(plant_id):
    """Ladder rule 5: a PlantOperator may only act inside its own plant."""
    if is_plant_operator() and plant_id is not None and plant_id != g.user_id:
        raise ApiError(
            "ERR_PLANT_SCOPE_VIOLATION",
            "A PlantOperator may only act on resources of its own plant.",
        )
