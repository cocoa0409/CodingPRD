"""Authentication / RBAC middleware (PRD section 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "Redeveloper",
    "EnvironmentalConsultant",
    "Insurer",
    "StateAgencyReviewer",
    "Lender",
    "ProgramAdmin",
)

ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Validate the identity headers first, then the endpoint's role list.

    Header presence (priority 1) is checked before anything else in the
    request, including path resolution; role membership is priority 2.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header missing or blank.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header missing or blank.")
    role = role.strip()
    if role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s may not call this endpoint." % role,
        )
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def endpoint(roles):
    """Decorator applying the auth/RBAC gate for one endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.user_id


def actor_role():
    return g.role
