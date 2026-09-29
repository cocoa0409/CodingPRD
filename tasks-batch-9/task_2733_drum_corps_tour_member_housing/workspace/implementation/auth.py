"""Authentication and role checks -- rungs 1 and 2 of the PRD 2.6 ladder."""
import functools

from flask import g, request

from errors import ApiError
from store import LOCK

# PRD 2.1: seven roles, spelled exactly.
ROLES = (
    "CorpsDirector",
    "MembershipCoordinator",
    "TourManager",
    "BusinessManager",
    "VolunteerScreener",
    "Member",
    "Volunteer",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def endpoint(roles):
    """Wrap a view with rung-1/rung-2 checks and the global store lock."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            role = request.headers.get(USER_ROLE_HEADER)
            # Rung 1 -- both headers present and the role is one of the seven.
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            # Rung 2 -- the acting role is authorized for this endpoint.
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.user_role = role
            with LOCK:
                return view(*args, **kwargs)

        wrapper.allowed_roles = allowed
        return wrapper

    return decorator


def acting_user_id():
    return g.user_id


def acting_role():
    return g.user_role
