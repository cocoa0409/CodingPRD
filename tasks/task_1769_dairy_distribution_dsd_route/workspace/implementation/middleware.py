"""Auth middleware: X-User-ID / X-User-Role header extraction, role checks,
and entity-backed ownership helpers per PRD §2.1 and SCAFFOLD validations 1-3.
"""

from flask import request

from db import DB
from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_OWNERSHIP_MISMATCH,
    err,
)

ROLES = {
    "TerritoryManager",
    "MarketAdministrator",
    "DistributorOwner",
    "RouteDriver",
    "StoreReceiver",
    "QualityInspector",
}


def require_auth():
    """Priority 1: headers present and role is a declared role name."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing or role not a declared role",
        )
    return user_id, role


def require_role(*roles):
    """Priority 2: caller's role is listed for the endpoint."""
    user_id, role = require_auth()
    if role not in roles:
        raise err(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this endpoint",
        )
    return user_id, role


def require_any():
    """Read authorization 'Any': every authenticated role may read."""
    return require_auth()


# ---------- entity-backed ownership helpers (priority 3) ----------

def owner_check_owner(user_id, distributor_id):
    """DistributorOwner: X-User-ID must equal the owning distributor id."""
    if user_id != distributor_id:
        raise err(
            ERR_OWNERSHIP_MISMATCH,
            "Caller does not own the target resource's distributor chain",
        )


def owner_check_store_owner(user_id, store):
    route = DB.routes.get(store["route_id"])
    owner_check_owner(user_id, route["distributor_id"] if route else None)


def owner_check_trip_owner(user_id, trip):
    route = DB.routes.get(trip["route_id"])
    owner_check_owner(user_id, route["distributor_id"] if route else None)


def owner_check_order_owner(user_id, order):
    store = DB.stores.get(order["store_id"])
    if store is None:
        owner_check_owner(user_id, None)
    owner_check_store_owner(user_id, store)


def owner_check_trip_driver(user_id, trip):
    """RouteDriver: X-User-ID must equal trip.driver_id."""
    if user_id != trip["driver_id"]:
        raise err(
            ERR_OWNERSHIP_MISMATCH,
            "Caller is not the trip's driver",
        )


def owner_check_store_receiver(user_id, store_id):
    """StoreReceiver: X-User-ID must equal the resource's store_id."""
    if user_id != store_id:
        raise err(
            ERR_OWNERSHIP_MISMATCH,
            "Caller is not the store for this resource",
        )
