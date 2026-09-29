"""Authentication / authorization (PRD §2.1, screening steps 1-2)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "PlantAdmin",
    "BlendEngineer",
    "QualityManager",
    "ExtrusionOperator",
    "PrintOperator",
    "ConvertingOperator",
)

ANY_ROLE = ROLES


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be recognized.",
        )
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorized for this endpoint." % role,
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    """Decorator applying screening steps 1 and 2 before the handler runs."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
