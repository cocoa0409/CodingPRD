"""Delivery endpoints: book, read, dispatch, complete, cancel + list."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from clock import to_iso8601_millis
from db import db, base_versioned, touch
from errors import err
from lookups import body, get_order, get_delivery, get_vehicle
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from validation import req_datetime

bp = Blueprint("deliveries", __name__)


def delivery_view(d):
    return {
        "id": d["id"],
        "order_id": d["order_id"],
        "vehicle_id": d["vehicle_id"],
        "nursery_id": d["nursery_id"],
        "window_start": to_iso8601_millis(d["window_start"]),
        "window_end": to_iso8601_millis(d["window_end"]),
        "bulk_volume_cubic_yards": d["bulk_volume_cubic_yards"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def _order_bulk_volume(order_id):
    """Total CUBIC_YARD volume of BULK_MATERIAL lines on the order."""
    total = 0
    for ol in db.order_lines.values():
        if ol["order_id"] != order_id:
            continue
        product = db.products.get(ol["product_id"])
        if product and product["category"] == "BULK_MATERIAL":
            total += ol["qty"]
    return total


@bp.post("/orders/<order_id>/deliveries")
@require_roles("InventoryManager")
def book_delivery(order_id):
    order = get_order(order_id)
    data = body()
    vehicle_id = data.get("vehicle_id")
    if not isinstance(vehicle_id, str) or not vehicle_id:
        err(errors.ERR_INVALID_REQUEST, "vehicle_id required")
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")
    if not (window_end > window_start):
        err(errors.ERR_INVALID_REQUEST, "window_end must be after window_start")

    # Body FK existence + same-nursery (priority 4)
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None or vehicle["nursery_id"] != order["nursery_id"]:
        err(errors.ERR_VEHICLE_NOT_FOUND, "vehicle not found in nursery")

    # Vehicle window conflict (priority 11): buffered-adjacency.
    # busy interval = [start, end + turnaround); collide iff intervals intersect.
    turnaround = timedelta(minutes=vehicle["turnaround_minutes"])
    new_busy_start = window_start
    new_busy_end = window_end + turnaround
    for d in db.deliveries.values():
        if d["vehicle_id"] != vehicle_id:
            continue
        if d["status"] == "CANCELLED":
            continue
        existing_busy_start = d["window_start"]
        existing_busy_end = d["window_end"] + turnaround
        if new_busy_start < existing_busy_end and existing_busy_start < new_busy_end:
            err(errors.ERR_VEHICLE_WINDOW_CONFLICT, "vehicle window conflict")

    # Capacity (priority 12)
    bulk_volume = _order_bulk_volume(order_id)
    if bulk_volume > vehicle["capacity_cubic_yards"]:
        err(errors.ERR_VEHICLE_CAPACITY_EXCEEDED, "bulk volume exceeds capacity")

    d = base_versioned()
    d.update({
        "order_id": order_id,
        "vehicle_id": vehicle_id,
        "nursery_id": order["nursery_id"],
        "window_start": window_start,
        "window_end": window_end,
        "bulk_volume_cubic_yards": bulk_volume,
        "status": "SCHEDULED",
    })
    db.deliveries[d["id"]] = d
    return created(delivery_view(d))


@bp.get("/orders/<order_id>/deliveries")
@require_roles("InventoryManager", "SalesClerk")
def list_order_deliveries(order_id):
    get_order(order_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [d for d in db.deliveries.values() if d["order_id"] == order_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: d["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([delivery_view(d) for d in page], limit, offset, total)


@bp.get("/deliveries/<delivery_id>")
@require_roles("InventoryManager", "SalesClerk")
def read_delivery(delivery_id):
    d = get_delivery(delivery_id)
    return ok(delivery_view(d))


@bp.post("/deliveries/<delivery_id>/dispatch")
@require_roles("InventoryManager")
def dispatch_delivery(delivery_id):
    d = get_delivery(delivery_id)
    if d["status"] != "SCHEDULED":
        err(errors.ERR_DELIVERY_NOT_SCHEDULED, "delivery not SCHEDULED")
    order = db.orders.get(d["order_id"])
    if order is None or order["fulfillment_status"] != "ALLOCATED":
        err(errors.ERR_ORDER_NOT_ALLOCATED, "parent order not ALLOCATED")
    d["status"] = "DISPATCHED"
    touch(d)
    return ok(delivery_view(d))


@bp.post("/deliveries/<delivery_id>/complete")
@require_roles("InventoryManager")
def complete_delivery(delivery_id):
    d = get_delivery(delivery_id)
    if d["status"] != "DISPATCHED":
        err(errors.ERR_DELIVERY_NOT_DISPATCHED, "delivery not DISPATCHED")
    d["status"] = "DELIVERED"
    touch(d)
    return ok(delivery_view(d))


@bp.post("/deliveries/<delivery_id>/cancel")
@require_roles("InventoryManager", "SalesClerk")
def cancel_delivery(delivery_id):
    d = get_delivery(delivery_id)
    if d["status"] not in ("SCHEDULED", "DISPATCHED"):
        err(errors.ERR_DELIVERY_NOT_CANCELLABLE, "delivery not cancellable")
    d["status"] = "CANCELLED"
    touch(d)
    return ok(delivery_view(d))
