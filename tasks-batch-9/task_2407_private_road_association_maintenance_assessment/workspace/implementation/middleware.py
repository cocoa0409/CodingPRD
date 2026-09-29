"""Identity, roles and the separation of association offices (PRD 2.1)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "AssociationSecretary",
    "AssessmentClerk",
    "BoardTreasurer",
    "RoadCommissioner",
    "MemberOwner",
    "Contractor",
)

READ_ALL = (
    "AssociationSecretary",
    "AssessmentClerk",
    "BoardTreasurer",
    "RoadCommissioner",
    "MemberOwner",
)


def auth(*allowed_roles):
    """Checks 1-3 of PRD 2.10, in that exact order."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or not str(user_id).strip():
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or blank.")
            if role is None or not str(role).strip():
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or blank.")
            role = str(role).strip()
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role does not name a recognised role.")
            if role not in allowed_roles:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE",
                    "Role %s is not authorised for this endpoint." % role,
                )
            g.user_id = str(user_id).strip()
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return g.user_id


def actor_role():
    return g.role
