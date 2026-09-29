"""Header authentication, role authorization and ownership checks (PRD 2.1)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "ArtisticDirector",
    "RegistrarStaff",
    "FinanceOfficer",
    "Panelist",
    "Guardian",
)

ALL_ROLES = list(ROLES)
# Every role except Panelist: the musician-read and musician-list endpoints.
NO_PANELIST = ["ArtisticDirector", "RegistrarStaff", "FinanceOfficer", "Guardian"]


def endpoint(*roles):
    """Decorator: header validity, then role authorization for this endpoint."""

    allowed = set(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in ROLES:
                raise ApiError("ERR_MISSING_AUTH_HEADERS",
                               "X-User-ID and a valid X-User-Role are required.")
            if user_role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED",
                               "Role %s may not call this endpoint." % user_role)
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting():
    return g.user_id, g.user_role


def require_guardian_owns(member_id):
    """Guardian identity is entity-backed: X-User-ID must be the member's id."""
    if g.user_role == "Guardian" and g.user_id != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting guardian does not own this resource.")


def require_panelist_owns(panelist_id):
    if g.user_role == "Panelist" and g.user_id != panelist_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting panelist does not own this submission.")
