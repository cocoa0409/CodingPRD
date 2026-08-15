"""Store endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_int, opt_enum, make_entity, touch, lookup,
    list_response, public,
)
from response import success_object
from errors import ApiError, ERR_INVALID_STATE

bp = Blueprint("stores", __name__)


def _with_ratio(store):
    out = dict(store)
    delivered = int(store.get("lifetime_delivered_units") or 0)
    stale = int(store.get("lifetime_stale_units") or 0)
    denom = max(1, delivered)
    out["stale_ratio"] = stale / denom
    return out


@bp.route("/bakery/stores", methods=["POST"])
def create_store():
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    data = body()
    plant_id = req_string(data, "plant_id")
    lookup(DB.plants, plant_id, "plant")
    name = req_string(data, "name")
    lead_time_hours = req_int(data, "lead_time_hours", min_value=1)
    min_remaining_life_hours_on_delivery = req_int(
        data, "min_remaining_life_hours_on_delivery", min_value=0, allow_zero=True
    )
    shelf_capacity_units = req_int(data, "shelf_capacity_units", min_value=1)
    stale_credit_tier = opt_enum(data, "stale_credit_tier", {"STANDARD", "LIMITED"}, "STANDARD")

    store = make_entity({
        "plant_id": plant_id,
        "name": name,
        "lead_time_hours": lead_time_hours,
        "min_remaining_life_hours_on_delivery": min_remaining_life_hours_on_delivery,
        "shelf_capacity_units": shelf_capacity_units,
        "stale_credit_tier": stale_credit_tier,
        "status": "ACTIVE",
        "credit_balance_cents": 0,
        "lifetime_delivered_units": 0,
        "lifetime_stale_units": 0,
        "stale_ratio": 0,
    })
    DB.stores[store["id"]] = store
    return success_object(_with_ratio(store), status=201)


@bp.route("/bakery/stores/<sid>", methods=["GET"])
def get_store(sid):
    get_auth()
    store = lookup(DB.stores, sid, "store")
    return success_object(_with_ratio(store))


@bp.route("/bakery/stores", methods=["GET"])
def list_stores():
    get_auth()
    filters = {
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
    }
    stores = [_with_ratio(s) for s in DB.stores.values()]
    return list_response(stores, filters)


@bp.route("/bakery/stores/<sid>/suspend", methods=["POST"])
def suspend_store(sid):
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    store = lookup(DB.stores, sid, "store")
    if store.get("status") != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Store is not ACTIVE", 409)
    store["status"] = "SUSPENDED"
    touch(store)
    return success_object(_with_ratio(store))


@bp.route("/bakery/stores/<sid>/reinstate", methods=["POST"])
def reinstate_store(sid):
    _, role = get_auth()
    require_role(role, {"PlantAdmin"})
    store = lookup(DB.stores, sid, "store")
    if store.get("status") != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Store is not SUSPENDED", 409)
    store["status"] = "ACTIVE"
    touch(store)
    return success_object(_with_ratio(store))
