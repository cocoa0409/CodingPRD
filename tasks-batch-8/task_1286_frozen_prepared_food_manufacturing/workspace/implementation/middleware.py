"""Auth header extraction and role authorization (PRD §2.1, SCAFFOLD §1.7)."""

from functools import wraps

from flask import request

from db import LOCK
from errors import ApiError

ROLES = {
    "PlantManager",
    "ProductionPlanner",
    "LineOperator",
    "QATechnician",
    "QAManager",
    "WarehouseLead",
    "CoPackCustomer",
}

PLANT_ROLES = ROLES - {"CoPackCustomer"}
ALL_ROLES = ROLES


def current_identity():
    """Pipeline stage 1: X-User-ID and X-User-Role present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip():
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers must be present",
        )
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Role '%s' is not a declared role" % role)
    return user_id.strip(), role


def require_role(role, allowed):
    """Pipeline stage 2: role permitted on this endpoint."""
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", "Role '%s' is not permitted on this endpoint" % role
        )


def endpoint(allowed_roles):
    """Decorator: serialize access through the store lock, run auth (stage 1)
    then role authorization (stage 2), then call the handler with
    (user_id, role)."""

    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            with LOCK:
                user_id, role = current_identity()
                require_role(role, allowed_roles)
                return fn(user_id, role, *args, **kwargs)

        return inner

    return wrapper
