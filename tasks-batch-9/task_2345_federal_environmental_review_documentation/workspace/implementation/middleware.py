"""Authentication and role authorisation (PRD 2.1, rejection bands 1 and 2)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "PolicyAdmin",
    "NepaCoordinator",
    "ResourceSpecialist",
    "ReviewingOfficial",
    "AgencyLiaison",
    "DecidingOfficial",
    "ObjectionReviewingOfficer",
    "PublicCommenter",
)
ROLE_SET = set(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or role not in ROLE_SET:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and a recognised X-User-Role header are required",
            401,
        )
    g.user_id = user_id
    g.role = role


def authorize(roles):
    if g.role not in roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "role %s is not permitted for this operation" % g.role,
            403,
        )


def endpoint(bp, rule, methods, roles):
    """Register a route that authenticates then authorises before dispatch."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            authenticate()
            authorize(roles)
            return fn(**kwargs)

        bp.add_url_rule(rule, endpoint=fn.__name__, view_func=wrapper, methods=methods)
        return wrapper

    return decorator
