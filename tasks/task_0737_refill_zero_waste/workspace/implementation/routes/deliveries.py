from datetime import timedelta
from flask import Blueprint, request

import store
import response
import serialize
import services
from errors import ApiError
from helpers import (endpoint, get_body, field, lookup, require_fk, stamp_new,
                     touch, paginate, owner_check)

bp = Blueprint("deliveries", __name__)

TURNAROUND_BUFFER = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# DeliveryVehicle
# ---------------------------------------------------------------------------
@bp.post("/v1/delivery-vehicles")
@endpoint(["InventoryManager"])
def create_vehicle():
    body = get_body()
    plate = field(body, "plate", required=True, kind="str")
    capacity_orders = field(body, "capacity_orders", required=True, kind="int")
    for v in store.DB["vehicles"].values():
        if v["plate"] == plate:
            raise ApiError("ERR_DUPLICATE_EMAIL", "vehicle plate already registered")
    rec = {"plate": plate, "capacity_orders": capacity_orders}
    stamp_new(rec)
    store.DB["vehicles"][rec["id"]] = rec
    return response.created(serialize.vehicle_out(rec))


@bp.get("/v1/delivery-vehicles/<vehicle_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_vehicle(vehicle_id):
    return response.ok(serialize.vehicle_out(lookup("vehicles", vehicle_id)))


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
@bp.post("/v1/deliveries")
@endpoint(["Member", "StoreClerk"])
def create_delivery():
    body = get_body()
    order_id = field(body, "order_id", required=True, kind="str")
    vehicle_id = field(body, "vehicle_id", required=True, kind="str")
    start = field(body, "window_start_at", required=True, kind="datetime")
    end = field(body, "window_end_at", required=True, kind="datetime")
    if end <= start:
        raise ApiError("ERR_VALIDATION", "window_end_at must be after window_start_at")
    order = require_fk("orders", order_id)
    require_fk("vehicles", vehicle_id)
    owner_check(order["member_id"])
    # Temporal (priority 7): closed interval + turnaround buffer on the vehicle
    for d in store.DB["deliveries"].values():
        if d["vehicle_id"] == vehicle_id and d["status"] != "CANCELLED":
            if start < d["window_end_at"] + TURNAROUND_BUFFER and d["window_start_at"] < end + TURNAROUND_BUFFER:
                raise ApiError("ERR_VEHICLE_WINDOW_CONFLICT",
                               "delivery window within turnaround buffer of another window")
    rec = {
        "order_id": order_id,
        "vehicle_id": vehicle_id,
        "member_id": order["member_id"],
        "window_start_at": start,
        "window_end_at": end,
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    store.DB["deliveries"][rec["id"]] = rec
    return response.created(serialize.delivery_out(rec))


@bp.get("/v1/deliveries/<delivery_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_delivery(delivery_id):
    return response.ok(serialize.delivery_out(lookup("deliveries", delivery_id)))


@bp.get("/v1/deliveries")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def list_deliveries():
    filters = {
        "order_id": request.args.get("order_id"),
        "vehicle_id": request.args.get("vehicle_id"),
        "member_id": request.args.get("member_id"),
        "status": request.args.get("status"),
    }
    recs = list(store.DB["deliveries"].values())
    for key, val in filters.items():
        if val is not None:
            recs = [d for d in recs if d[key] == val]
    page, limit, offset, total = paginate(recs)
    return response.listing([serialize.delivery_out(d) for d in page], limit, offset, total)


@bp.post("/v1/deliveries/<delivery_id>/dispatch")
@endpoint(["StoreClerk", "InventoryManager"])
def dispatch_delivery(delivery_id):
    d = lookup("deliveries", delivery_id)
    if d["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "delivery must be SCHEDULED to dispatch")
    order = store.DB["orders"][d["order_id"]]
    if order["fulfillment_status"] != "FILLED" or order["payment_status"] != "CAPTURED":
        raise ApiError("ERR_DELIVERY_ORDER_NOT_READY", "order is not FILLED and CAPTURED")
    d["status"] = "DISPATCHED"
    touch(d)
    return response.ok(serialize.delivery_out(d))


@bp.post("/v1/deliveries/<delivery_id>/deliver")
@endpoint(["StoreClerk", "InventoryManager"])
def deliver_delivery(delivery_id):
    d = lookup("deliveries", delivery_id)
    if d["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "delivery must be DISPATCHED to deliver")
    d["status"] = "DELIVERED"
    touch(d)
    order = store.DB["orders"][d["order_id"]]
    order["fulfillment_status"] = "COMPLETED"
    touch(order)
    return response.ok(serialize.delivery_out(d))


@bp.post("/v1/deliveries/<delivery_id>/return-received")
@endpoint(["StoreClerk", "InventoryManager"])
def return_received(delivery_id):
    d = lookup("deliveries", delivery_id)
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "delivery must be DELIVERED to receive a return")
    d["status"] = "RETURNED"
    touch(d)
    # Close the container return loop: each IN_USE container on the order -> RETURNED + refund
    seen = set()
    for l in services.final_lines(d["order_id"]):
        cid = l["container_id"]
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        c = store.DB["containers"].get(cid)
        if c is not None and c["status"] == "IN_USE":
            c["status"] = "RETURNED"
            touch(c)
            services.append_ledger(
                c["member_id"], "DEPOSIT_REFUND",
                wallet_delta=c["deposit_cents"], liability_delta=-c["deposit_cents"],
                source_kind="DELIVERY", source_id=d["id"], memo="deposit refund on delivery return",
            )
    return response.ok(serialize.delivery_out(d))


@bp.post("/v1/deliveries/<delivery_id>/cancel")
@endpoint(["StoreClerk", "InventoryManager"])
def cancel_delivery(delivery_id):
    d = lookup("deliveries", delivery_id)
    if d["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "delivery must be SCHEDULED to cancel")
    d["status"] = "CANCELLED"
    touch(d)
    return response.ok(serialize.delivery_out(d))
