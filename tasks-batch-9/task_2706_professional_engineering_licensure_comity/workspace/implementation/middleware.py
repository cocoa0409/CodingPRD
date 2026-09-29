"""Authentication and role-based access control (PRD 2.1, ladder rungs 1-2)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "Applicant",
    "SupervisingEngineer",
    "Licensee",
    "FirmAdmin",
    "BoardReviewer",
    "BoardLicensingOfficer",
    "BoardInvestigator",
    "BoardSecretary",
    "TestingService",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "%s header is required" % USER_ID_HEADER)
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "%s header is required" % USER_ROLE_HEADER)
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unknown role %r" % role)
    g.user_id = str(user_id).strip()
    g.user_role = role
    return g.user_id, g.user_role


def authorize(allowed_roles):
    if g.user_role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "role %s may not perform this operation" % g.user_role,
        )


def endpoint(*allowed_roles):
    """Wrap a view: rung 1 authentication, then rung 2 authorization."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed_roles)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


def role():
    return g.user_role
