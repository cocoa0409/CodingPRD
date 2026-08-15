"""Store endpoints: onboard, get, patch (OCC), deactivate/reactivate with cascades."""

from flask import Blueprint

from db import DB
from middleware import require_role, require_any, owner_check_owner
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int,
    base_fields, paginate, err, touch, apply_changes,
)
from response import success_object
from errors import (
    ERR_INVALID_REQUEST, ERR_ROUTE_NOT_FOUND, ERR_STORE_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH, ERR_STALE_STORE_VERSION,
    ERR_STORE_NOT_ACTIVE, ERR_ROUTE_NOT_ACTIVE, ERR_STORE_HAS_CONFIRMED_ORDERS,
)
from serializers import serialize_store
from services import refresh_trip_loaded_cases

bp = Blueprint("stores", __name__)

CONFIG_FIELDS = {
    "credit_limit_cents", "pull_window_days", "crate_deposit_cents",
    "merchandising_rate_cents_per_min", "free_merchandising_minutes",
    "dock_open_min", "dock_close_min",
}


def get_store_or_404(store_id):
    s = DB.stores.get(store_id)
    if s is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    return s


@bp.post("/dairy/stores")
def create_store():
    user_id, _role = require_role("DistributorOwner")
    body = get_json_body()
    allowed = {"route_id", "store_code", "name"} | CONFIG_FIELDS
    check_unknown_fields(body, allowed)
    require_fields(body, ["route_id", "store_code", "name"])
    route = DB.routes.get(body["route_id"])
    if route is None:
        raise err(ERR_ROUTE_NOT_FOUND, "Route id not found")
    owner_check_owner(user_id, route["distributor_id"])
    store_code = body["store_code"]
    if not isinstance(store_code, str):
        raise err(ERR_INVALID_REQUEST, "store_code must be a string")
    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_REQUEST, "name must be a string")
    for s in DB.stores.values():
        if s["store_code"] == store_code:
            raise err(ERR_INVALID_REQUEST, "store_code must be unique")
    cfg = {}
    for f in CONFIG_FIELDS:
        v = opt_int(body, f, ge=0)
        if v is not None:
            cfg[f] = v
    s = base_fields()
    s.update({
        "route_id": route["id"],
        "store_code": store_code,
        "name": name,
        "credit_limit_cents": cfg.get("credit_limit_cents", 0),
        "pull_window_days": cfg.get("pull_window_days", 4),
        "crate_deposit_cents": cfg.get("crate_deposit_cents", 400),
        "merchandising_rate_cents_per_min": cfg.get("merchandising_rate_cents_per_min", 0),
        "free_merchandising_minutes": cfg.get("free_merchandising_minutes", 15),
        "dock_open_min": cfg.get("dock_open_min", 480),
        "dock_close_min": cfg.get("dock_close_min", 720),
        "status": "ACTIVE",
        "crate_balance": 0,
        "open_ar_cents": 0,
        "deposit_liability_cents": 0,
    })
    DB.stores[s["id"]] = s
    return success_object(serialize_store(s), status=201)


@bp.get("/dairy/stores/<storeId>")
def get_store(storeId):
    require_any()
    return success_object(serialize_store(get_store_or_404(storeId)))


@bp.patch("/dairy/stores/<storeId>")
def patch_store(storeId):
    user_id, _role = require_role("DistributorOwner")
    s = get_store_or_404(storeId)
    owner_check_store_owner_route(user_id, s)
    body = get_json_body()
    allowed = {"expected_store_version"} | CONFIG_FIELDS
    check_unknown_fields(body, allowed)
    require_fields(body, ["expected_store_version"])
    expected = opt_int(body, "expected_store_version")
    for f in CONFIG_FIELDS:
        opt_int(body, f, ge=0)
    if expected != s["version"]:
        raise err(ERR_STALE_STORE_VERSION, "expected_store_version does not match the store's current version")
    changes = {f: body[f] for f in CONFIG_FIELDS if f in body and body[f] is not None}
    if "crate_deposit_cents" in changes:
        # Deposit liability derives from the deposit rate; recompute now.
        changes["deposit_liability_cents"] = s["crate_balance"] * changes["crate_deposit_cents"]
    for k, v in changes.items():
        s[k] = v
    touch(s)  # a successful patch increments Store.version by exactly 1
    return success_object(serialize_store(s))


def owner_check_store_owner_route(user_id, store):
    route = DB.routes.get(store["route_id"])
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the store's route")


@bp.post("/dairy/stores/<storeId>/deactivate")
def deactivate_store(storeId):
    user_id, _role = require_role("DistributorOwner")
    s = get_store_or_404(storeId)
    owner_check_store_owner_route(user_id, s)
    if s["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store must be ACTIVE to deactivate")
    has_confirmed = any(
        o["store_id"] == s["id"] and o["fulfillment_status"] == "CONFIRMED"
        for o in DB.orders.values()
    )
    if has_confirmed:
        raise err(ERR_STORE_HAS_CONFIRMED_ORDERS, "Store has orders in CONFIRMED")
    s["status"] = "INACTIVE"
    touch(s)
    # Cascade depth 2-3: PLANNED orders -> CANCELLED; reserved cases released.
    affected_trips = set()
    for o in DB.orders.values():
        if o["store_id"] == s["id"] and o["fulfillment_status"] == "PLANNED":
            o["fulfillment_status"] = "CANCELLED"
            touch(o)
            affected_trips.add(o["trip_id"])
    for tid in affected_trips:
        t = DB.trips.get(tid)
        if t is not None:
            refresh_trip_loaded_cases(t)
    return success_object(serialize_store(s))


@bp.post("/dairy/stores/<storeId>/reactivate")
def reactivate_store(storeId):
    user_id, _role = require_role("DistributorOwner")
    s = get_store_or_404(storeId)
    owner_check_store_owner_route(user_id, s)
    if s["status"] != "INACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store must be INACTIVE to reactivate")
    route = DB.routes.get(s["route_id"])
    if route is None or route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "Store's route must be ACTIVE to reactivate")
    apply_changes(s, {"status": "ACTIVE"})
    return success_object(serialize_store(s))
