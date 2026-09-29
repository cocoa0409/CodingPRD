"""Authentication, RBAC and the shared endpoint wrapper."""
from functools import wraps

from flask import g, request

import responses
import serializers
import store
from constants import ROLES
from errors import ApiError

ALL_ROLES = list(ROLES)


def identify():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return str(uid).strip(), role


def endpoint(roles, mutating=True):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = identify()
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = uid
            g.role = role
            g.touched = set()
            snap = serializers.snapshot() if mutating else None
            result = fn(*args, **kwargs)
            if mutating:
                serializers.finalize(snap, g.touched)
            return responses.render(result)
        return wrapper
    return deco


def explicit_touch(row):
    """Bump a row's version even though its content did not change."""
    store.touch(row)
    if hasattr(g, "touched"):
        g.touched.add(row["id"])


def require_owner(owner_id, entity_roles=("ResidentAssistant", "Student")):
    """Ownership check (PRD s2.1 closed list). Skipped for opaque roles."""
    if g.role not in entity_roles:
        return
    if owner_id is None:
        return
    if g.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_action_role(role_or_roles):
    allowed = (role_or_roles,) if isinstance(role_or_roles, str) else tuple(role_or_roles)
    if g.role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
