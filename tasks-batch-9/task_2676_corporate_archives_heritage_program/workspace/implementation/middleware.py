"""Identity header extraction and role authorisation (PRD 2.1)."""

import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "ArchivesDirector",
    "Archivist",
    "PreservationOfficer",
    "AccessServicesOfficer",
    "LegalCounsel",
    "Requester",
    "SystemOperator",
)


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The %s header is required." % USER_ID_HEADER)
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "The %s header is required." % USER_ROLE_HEADER)
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "'%s' is not a recognised role." % role)
    g.user_id = str(user_id).strip()
    g.user_role = role


def authorize(allowed):
    if allowed is None:
        return
    if g.user_role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not perform this operation." % g.user_role,
        )


def endpoint(roles=None):
    """Wrap a view with rung 1 (authentication) then rung 2 (authorisation)."""
    allowed = tuple(roles) if roles else None

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed)
            return view(*args, **kwargs)

        return wrapper

    return decorator
