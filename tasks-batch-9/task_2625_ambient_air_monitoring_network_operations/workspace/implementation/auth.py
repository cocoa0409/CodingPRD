"""Authentication and role authorisation (PRD sections 2.1 and 2.11).

Every request carries X-User-ID and X-User-Role.  Both headers must be present
and X-User-Role must name one of the five declared roles, otherwise
ERR_UNAUTHENTICATED (401).  A well-formed identity whose role is not authorised
for the method and path is ERR_UNAUTHORIZED (403).  All five roles are opaque
identities: X-User-ID is never resolved against any entity's id.
"""
import functools

from flask import request

from errors import ApiError

ROLES = (
    "NetworkAdmin",
    "FieldTechnician",
    "QaOfficer",
    "ProgramManager",
    "EpaRegionalReviewer",
)

ALL_ROLES = list(ROLES)


def actor():
    return request.headers.get("X-User-ID")


def actor_role():
    return request.headers.get("X-User-Role")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    return user_id, role


def require(*roles):
    """Decorator: authentication first, then role authorisation."""
    allowed = set(roles) if roles else set(ROLES)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _uid, role = authenticate()
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not authorised for %s %s." % (role, request.method, request.path),
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
