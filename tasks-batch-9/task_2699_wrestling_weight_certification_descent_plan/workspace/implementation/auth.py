"""Header authentication, endpoint authorization and request serialization."""

import functools
import threading

from flask import g, request

from errors import ApiError

ROLES = (
    "StateOffice",
    "Assessor",
    "TeamCoach",
    "WeighInOfficial",
    "MedicalReviewer",
)

# The Flask development server is threaded; every request mutates the shared
# in-memory store, and cascades must be applied atomically, so requests are
# serialized behind one re-entrant lock.
_LOCK = threading.RLock()


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "Header 'X-User-ID' is required.")
    if not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Header 'X-User-Role' must name one of the five declared roles.",
        )
    return user_id, role


def endpoint(*roles):
    """Wrap a view: authenticate, authorize, then run under the store lock."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role '%s' is not authorized for this endpoint." % role,
                )
            g.user_id = user_id
            g.role = role
            with _LOCK:
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.get("user_id"), g.get("role")


def user_id():
    return g.get("user_id")


def role():
    return g.get("role")


def owns_team(team_id):
    """TeamCoach ownership: X-User-ID is the acting Team's id."""
    if role() != "TeamCoach":
        return True
    return user_id() == team_id


def require_team_owner(team_id):
    if not owns_team(team_id):
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "The acting coach does not own the referenced team.",
        )


def require_assessor_owner(assessor_id):
    """Assessor ownership: X-User-ID is the acting Assessor's id."""
    if role() != "Assessor":
        return
    if user_id() != assessor_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER",
            "The acting assessor does not own the referenced resource.",
        )
