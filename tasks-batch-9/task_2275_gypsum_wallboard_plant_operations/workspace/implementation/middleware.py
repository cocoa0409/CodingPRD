"""Authentication (band 1) and authorisation (band 2) per PRD 2.1 / 2.11."""

from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "PlantAdmin",
    "MaterialsController",
    "ProductionScheduler",
    "QualityInspector",
    "QualityManager",
    "MaintenancePlanner",
    "PlantManager",
)

ANY = "ANY"


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "valid X-User-ID and X-User-Role headers are required")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def authorize(allowed):
    user_id, role = authenticate()
    if allowed != ANY and role not in allowed:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return user_id, role


def guard(allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authorize(allowed)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return getattr(g, "user_id", None)
