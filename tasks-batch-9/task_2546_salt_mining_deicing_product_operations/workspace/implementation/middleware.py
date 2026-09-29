"""Authentication (stage 1), authorisation (stage 2) and ownership (stage 4)."""

from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_DEPOT_NOT_OWNED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

ROLES = (
    "MinePlanner",
    "GroundControlEngineer",
    "QualityLab",
    "LogisticsPlanner",
    "ContractAdministrator",
    "ComplianceOfficer",
    "DepotManager",
)

ALL_ROLES = set(ROLES)

DEPOT_MANAGER = "DepotManager"


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-ID header is required")
    if role is None or not str(role).strip():
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-Role header is required")
    role = role.strip()
    if role not in ALL_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-Role '%s' is not a recognised role" % role)
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def auth(*allowed_roles):
    allowed = set(allowed_roles) or set(ALL_ROLES)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED, 403,
                    "role %s may not perform this operation" % role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def is_depot_manager():
    return g.get("role") == DEPOT_MANAGER


def require_depot_ownership(depot_id):
    """Stage 4. Only enforced for the entity-backed DepotManager role."""
    if not is_depot_manager():
        return
    if depot_id is None:
        return
    if g.get("user_id") != depot_id:
        raise ApiError(ERR_DEPOT_NOT_OWNED, 403,
                       "the acting depot manager does not own depot %s" % depot_id)


def require_distinct_actor(other_user_id, message):
    """Stage 3 segregation of duties."""
    if other_user_id is None:
        return
    if g.get("user_id") == other_user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, message)
