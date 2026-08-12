"""Delivery window endpoints (PRD §3.4)."""

from datetime import date

from flask import Blueprint, request

import errors
from clock import clock
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import serialize_window
from util import (
    dec,
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_int,
    require_number,
    require_str,
    touch,
)

bp = Blueprint("delivery_windows", __name__)


def _get_window_or_404(wid):
    w = db.delivery_windows.get(wid)
    if not w:
        raise errors.not_found(f"DeliveryWindow {wid} not found")
    return w


def _check_overlap(route_id, service_date, start_hour, end_hour, exclude_id=None):
    """Half-open interval overlap on same route/date."""
    for w in db.delivery_windows.values():
        if w["route_id"] != route_id or w["service_date"] != service_date:
            continue
        if exclude_id and w["id"] == exclude_id:
            continue
        if w["status"] == "CANCELLED":
            continue
        # overlap iff not (end <= other.start or start >= other.end)
        if not (end_hour <= w["start_hour"] or start_hour >= w["end_hour"]):
            raise errors.window_overlap()


@bp.post("/api/v1/delivery-windows")
def create_window():
    require_roles("RoutePlanner")
    body = get_json_body()
    route_id = require_str(body, "route_id")
    route = db.delivery_routes.get(route_id)
    if not route:
        raise errors.referenced_not_found(f"DeliveryRoute {route_id} not found")
    service_date = require_str(body, "service_date")
    start_hour = require_int(body, "start_hour")
    end_hour = require_int(body, "end_hour")
    capacity = require_number(body, "capacity_cord_equivalent")

    if not (0 <= start_hour <= 23) or not (0 <= end_hour <= 23):
        raise errors.validation("start_hour/end_hour must be in [0, 23]")
    # Temporal: service_date not in the past; end_hour > start_hour
    try:
        sd = date(int(service_date[0:4]), int(service_date[5:7]), int(service_date[8:10]))
    except (ValueError, IndexError):
        raise errors.validation("service_date must be ISO YYYY-MM-DD")
    now = clock.now()
    today = date(now.year, now.month, now.day)
    if sd < today:
        raise errors.window_closed("service_date is in the past")
    if end_hour <= start_hour:
        raise errors.window_closed("end_hour must be strictly greater than start_hour")
    # Capacity hierarchy
    if dec(capacity) > dec(route["capacity_cord_equivalent"]):
        raise errors.capacity_mismatch()
    # Overlap
    _check_overlap(route_id, service_date, start_hour, end_hour)

    ts = now_iso()
    wid = new_id()
    window = {
        "id": wid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "route_id": route_id,
        "service_date": service_date,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "capacity_cord_equivalent": capacity,
        "committed_cord_equivalent": 0,
        "status": "OPEN",
    }
    db.delivery_windows[wid] = window
    return success_object(serialize_window(window), status=201)


@bp.get("/api/v1/delivery-windows/<wid>")
def get_window(wid):
    require_roles("RoutePlanner", "OperationsManager", "CustomerService", "Driver", "Customer")
    return success_object(serialize_window(_get_window_or_404(wid)))


@bp.get("/api/v1/delivery-windows")
def list_windows():
    require_roles("RoutePlanner", "OperationsManager", "CustomerService", "Driver", "Customer")
    limit, offset = parse_pagination()
    items = list(db.delivery_windows.values())
    for f in ("route_id", "service_date", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [w for w in items if str(w.get(f)) == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_window(w) for w in page], total, limit, offset)


@bp.post("/api/v1/delivery-windows/<wid>/close")
def close_window(wid):
    require_roles("RoutePlanner")
    w = _get_window_or_404(wid)
    if w["status"] != "OPEN":
        raise errors.invalid_state("Window is not OPEN")
    w["status"] = "CLOSED"
    touch(w)
    return success_object(serialize_window(w))


@bp.post("/api/v1/delivery-windows/<wid>/lock")
def lock_window(wid):
    require_roles("RoutePlanner")
    w = _get_window_or_404(wid)
    if w["status"] not in ("OPEN", "CLOSED"):
        raise errors.invalid_state("Window cannot be locked from current state")
    # All SCHEDULED orders in this window must be PAID
    for o in db.orders.values():
        if o.get("delivery_window_id") == wid and o["fulfillment_status"] == "SCHEDULED":
            if o["payment_status"] != "PAID":
                raise errors.invalid_state("All scheduled orders must be PAID before locking")
    w["status"] = "LOCKED"
    touch(w)
    return success_object(serialize_window(w))


@bp.post("/api/v1/delivery-windows/<wid>/cancel")
def cancel_window(wid):
    require_roles("RoutePlanner")
    w = _get_window_or_404(wid)
    if w["status"] not in ("OPEN", "CLOSED"):
        raise errors.invalid_state("Window cannot be cancelled from current state")
    for o in db.orders.values():
        if o.get("delivery_window_id") == wid and o["fulfillment_status"] in (
            "SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED"
        ):
            raise errors.invalid_state("Window holds active orders")
    # CONFIRMED orders keep status but lose window binding
    for o in db.orders.values():
        if o.get("delivery_window_id") == wid and o["fulfillment_status"] == "CONFIRMED":
            o["delivery_window_id"] = None
            touch(o)
    w["status"] = "CANCELLED"
    touch(w)
    return success_object(serialize_window(w))
