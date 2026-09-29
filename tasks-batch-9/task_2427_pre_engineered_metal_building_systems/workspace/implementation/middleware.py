"""Authentication / RBAC middleware (PRD 2.1) and the per-request lock."""

import functools

from flask import g, request

from constants import ALL_ROLES
from errors import ApiError
from store import LOCK

ANY = "ANY"


def roles_required(*allowed):
    """Precedence bands 1 and 2 of PRD 2.5.

    Band 1: both X-User-ID and X-User-Role present and the role recognised.
    Band 2: the acting role listed for the endpoint.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if ANY not in allowed and role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.user_role = role
            with LOCK:
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id
