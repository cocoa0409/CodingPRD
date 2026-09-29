"""Operator identity, role authority and store scoping (PRD sections 2.1, 2.11)."""

from functools import wraps

from flask import g, request

from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
ENERGY_MANAGER = "EnergyManager"
ENERGY_ANALYST = "EnergyAnalyst"
STORE_MANAGER = "StoreManager"
FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"
MAINTENANCE_TECH = "MaintenanceTech"
BMS_GATEWAY = "BmsGateway"

ALL_ROLES = [
    PLATFORM_ADMIN, ENERGY_MANAGER, ENERGY_ANALYST, STORE_MANAGER,
    FOOD_SAFETY_OFFICER, MAINTENANCE_TECH, BMS_GATEWAY,
]

# Every role except the gateway.
NON_GATEWAY_ROLES = [
    PLATFORM_ADMIN, ENERGY_MANAGER, ENERGY_ANALYST, STORE_MANAGER,
    FOOD_SAFETY_OFFICER, MAINTENANCE_TECH,
]

ENTITY_BACKED_ROLES = (STORE_MANAGER, BMS_GATEWAY)


def roles(*allowed):
    """Authenticate the caller and check its declared role for this endpoint."""
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            if user_id is None or user_id == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            role = request.headers.get("X-User-Role")
            if role not in allowed_set:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_store_scope(store_id):
    """An entity-backed caller may only act on its own store."""
    if g.role in ENTITY_BACKED_ROLES and g.user_id != store_id:
        raise ApiError("ERR_STORE_SCOPE_VIOLATION")
