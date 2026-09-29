"""Authentication and role authorization (PRD 2.1, validation priorities 1 and 2)."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_ROLE_NOT_PERMITTED, ERR_UNAUTHENTICATED

ROLES = (
    "ProjectCoordinator",
    "SolarContractor",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
    "AHJInspector",
)

# Roles whose X-User-ID identifies a persisted Party row.
PARTY_ROLES = ("SolarContractor", "RoofingContractor", "SolarOwner", "SystemOwner")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID header is required", 401)
    if role is None or str(role).strip() == "":
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role header is required", 401)
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role is not a recognized role", 401)
    g.actor_id = user_id
    g.actor_role = role
    return user_id, role


def endpoint(*roles):
    """Decorator applying validation priorities 1 and 2 before the handler runs."""

    allowed = set(roles)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    ERR_ROLE_NOT_PERMITTED,
                    "role %s may not call this endpoint" % role,
                    403,
                )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.get("actor_id")


def actor_role():
    return g.get("actor_role")
