"""Priority 10 / 20 / 22 of the validation ladder."""
from functools import wraps

from flask import g, request

from core import ALL_ROLES, DB, ENTITY_BACKED_ROLES, fail


def authenticate(allowed):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    # priority 10 — authentication
    if role is None or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role is required")
    if role in ENTITY_BACKED_ROLES and (user_id is None or not user_id.strip()):
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required for %s" % role)
    # priority 20 — authorization
    if role not in ALL_ROLES or role not in allowed:
        fail("ERR_UNAUTHORIZED", "%s may not call this endpoint" % role)
    # priority 22 — role / record agreement
    actor = None
    if role in ENTITY_BACKED_ROLES:
        actor = DB["associates"].get(user_id)
        if actor is None or actor["role_code"] != ENTITY_BACKED_ROLES[role]:
            fail("ERR_ROLE_CODE_MISMATCH", "X-User-ID does not match the claimed role")
    g.role = role
    g.actor = actor
    g.user_id = user_id if actor is not None else None
    return actor


def roles(*allowed):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return getattr(g, "actor", None)


def actor_id():
    return getattr(g, "user_id", None)


def role():
    return getattr(g, "role", None)
