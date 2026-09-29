"""Authentication, RBAC and actor resolution (PRD sections 2.1 and 2.12)."""

from functools import wraps

from flask import g, request

from core import ROLES, db
from errors import ApiError

ENTITY_BACKED = {"Exhibitor": "riders", "Judge": "officials", "Steward": "officials"}


def authenticate(allowed_roles):
    """Ladder bands 1 and 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def resolve_actor():
    """Ladder band 4: entity-backed identities must resolve to a stored row."""
    role = g.user_role
    collection_name = ENTITY_BACKED.get(role)
    if collection_name is None:
        return None
    collection = getattr(db, collection_name)
    row = collection.get(g.user_id)
    if row is None:
        raise ApiError("ERR_ACTOR_NOT_RECOGNIZED")
    return row


def endpoint(*allowed_roles):
    """Wrap a handler with header/role checks and per-request mutation tracking."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            g._dirty_ids = set()
            g._created = set()
            g._stamp = None
            user_id, role = authenticate(allowed_roles)
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
