"""Authentication, RBAC and supply-room scope (PRD 2.1, precedence 1/2/6)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "ContractAdmin",
    "MaterialsManager",
    "Clinician",
    "DistributionOperator",
    "ManufacturerRep",
)

ALL_ROLES = list(ROLES)


def endpoint(roles):
    """Decorator applying validation priority 1 (auth) then 2 (role)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or not str(user_id).strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role is None or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            g.user_id = user_id
            g.role = role
            if role not in roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def scope_check(supply_room_id):
    """Validation priority 6.

    Only a MaterialsManager is scope-checked; its X-User-ID is the id of the
    SupplyRoom it acts for.
    """
    if g.role != "MaterialsManager":
        return
    if supply_room_id is None or str(g.user_id) != str(supply_room_id):
        raise ApiError("ERR_SUPPLY_ROOM_SCOPE_VIOLATION")
