"""Authentication / authorisation bands 1, 2 and 6 (PRD §2.1, §2.6)."""
from functools import wraps

from flask import g, request

from constants import ROLES
from errors import fail

ANY_ROLE = tuple(ROLES)


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a recognised X-User-Role are required")
    g.user_id = user_id
    g.role = role


def auth(*roles):
    """Band 1 (401) then band 2 (403)."""
    allowed = roles if roles else ANY_ROLE

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in allowed:
                fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % g.role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def own(subscriber_id):
    """Band 6 — subscriber ownership of the resource chain being touched."""
    if g.role == "Subscriber" and g.user_id != subscriber_id:
        fail("ERR_UNAUTHORIZED", "Subscriber may only act on its own resources")
