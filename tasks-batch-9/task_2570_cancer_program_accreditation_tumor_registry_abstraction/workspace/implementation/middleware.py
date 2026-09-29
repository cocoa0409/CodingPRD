"""Auth header extraction, RBAC, and the endpoint wrapper (PRD 2.1, 2.11)."""

from functools import wraps

from flask import g, request

import db
from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "RegistryManager",
    "RegistryAbstractor",
    "QaReviewer",
    "AccreditationCoordinator",
    "StateRegistryLiaison",
    "CoCSurveyor",
)

ANY_ROLE = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def actor():
    return g.actor_id


def actor_role():
    return g.actor_role


def _authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHORIZED")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED")
    g.actor_id = user_id
    g.actor_role = role


def endpoint(roles):
    """Wrap a route: authenticate, authorize, run, then commit version bumps."""
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.actor_role not in allowed:
                raise ApiError("ERR_FORBIDDEN")
            result = fn(*args, **kwargs)
            db.commit()
            return result

        return wrapper

    return decorator
