"""CurbsideCheckIn endpoints."""

from flask import Blueprint

from db import db, stamp_common, touch
from errors import err
from middleware import require_auth, get_json_body
from response import object_response
from services.common import require_str, ref_or_404, get_or_404, ser_checkin
from services.derived import recompute_pickup_standing

bp = Blueprint("curbside", __name__)

ACTIVE_CHECKIN = {"ARRIVED", "BEING_LOADED"}


@bp.post("/curbside-checkins")
def create_checkin():
    user_id, role = require_auth({"Customer"})
    body = get_json_body()
    order_id = require_str(body, "order_id")
    store_id = require_str(body, "store_id")
    vehicle_description = require_str(body, "vehicle_description")
    # FK existence (priority 5)
    order = ref_or_404(db.orders, order_id, "order")
    store = ref_or_404(db.stores, store_id, "store")
    # ownership (priority 3): customer must own the order
    if order["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "customer does not own this order")

    # curbside capacity (priority 15)
    if store["active_curbside_count"] >= store["curbside_spaces"]:
        raise err("ERR_CURBSIDE_FULL", "no curbside spaces available")

    # duplicate active check-in (priority 16)
    for c in db.curbside_checkins.values():
        if c["order_id"] == order_id and c["checkin_status"] in ACTIVE_CHECKIN:
            raise err("ERR_DUPLICATE_CHECKIN",
                      "order already has an active curbside check-in")

    rec = {
        "order_id": order_id,
        "store_id": store_id,
        "vehicle_description": vehicle_description,
        "checkin_status": "ARRIVED",
    }
    stamp_common(rec)
    db.curbside_checkins[rec["id"]] = rec
    store["active_curbside_count"] += 1
    touch(store)
    return object_response(ser_checkin(rec), 201)


@bp.get("/curbside-checkins/<cid>")
def get_checkin(cid):
    require_auth({"Customer", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.curbside_checkins, cid)
    return object_response(ser_checkin(rec))


@bp.post("/curbside-checkins/<cid>/start-loading")
def start_loading(cid):
    require_auth({"StoreAssociate"})
    rec = get_or_404(db.curbside_checkins, cid)
    # state guard (priority 8)
    if rec["checkin_status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", "check-in is not ARRIVED")
    # order-verified requirement (priority 17)
    order = db.orders.get(rec["order_id"])
    if order is None or not order["verified"]:
        raise err("ERR_ORDER_NOT_VERIFIED", "parent order is not verified")
    rec["checkin_status"] = "BEING_LOADED"
    touch(rec)
    return object_response(ser_checkin(rec))


@bp.post("/curbside-checkins/<cid>/complete")
def complete_loading(cid):
    require_auth({"StoreAssociate"})
    rec = get_or_404(db.curbside_checkins, cid)
    if rec["checkin_status"] != "BEING_LOADED":
        raise err("ERR_INVALID_STATE", "check-in is not BEING_LOADED")
    order = db.orders.get(rec["order_id"])
    if order is None or order["fulfillment_status"] not in {"COMPLETED", "PARTIALLY_PICKED_UP"}:
        raise err("ERR_INVALID_STATE",
                  "order is not COMPLETED or PARTIALLY_PICKED_UP")
    rec["checkin_status"] = "COMPLETED"
    store = db.stores.get(rec["store_id"])
    if store is not None and store["active_curbside_count"] > 0:
        store["active_curbside_count"] -= 1
        touch(store)
    touch(rec)
    return object_response(ser_checkin(rec))


@bp.post("/curbside-checkins/<cid>/cancel")
def cancel_checkin(cid):
    user_id, role = require_auth({"StoreAssociate", "Customer"})
    rec = get_or_404(db.curbside_checkins, cid)
    # ownership (priority 3) for Customer
    if role == "Customer":
        order = db.orders.get(rec["order_id"])
        if order is None or order["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "customer does not own this check-in")
    if rec["checkin_status"] not in ACTIVE_CHECKIN:
        raise err("ERR_INVALID_STATE", "check-in is not active")
    rec["checkin_status"] = "CANCELLED"
    store = db.stores.get(rec["store_id"])
    if store is not None and store["active_curbside_count"] > 0:
        store["active_curbside_count"] -= 1
        touch(store)
    touch(rec)
    return object_response(ser_checkin(rec))
