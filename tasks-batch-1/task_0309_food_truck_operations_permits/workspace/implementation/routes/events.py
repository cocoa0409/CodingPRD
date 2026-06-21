"""Event endpoints, cancel cascade, and sales-by-event report (PRD §3.3, §3.10)."""

from flask import Blueprint

import errors
import serializers
import services
from db import db
from errors import err
from helpers import get_body, require_str, require_datetime, get_pagination, paginate
from lookups import get_event
from middleware import require_user_context, require_role
from response import ok_object, ok_array

bp = Blueprint("events", __name__)

WRITE_ROLES = {"Dispatcher", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}
REPORT_ROLES = {"Dispatcher", "PlatformAdmin"}


@bp.post("/events")
def create_event():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    name = require_str(body, "name")
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    if not (ends_at > starts_at):
        raise err(errors.ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    rec = db.new_record({
        "name": name,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "status": "SCHEDULED",
    })
    db.events[rec["id"]] = rec
    return ok_object(serializers.event(rec), 201)


@bp.get("/events")
def list_events():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    window, total = paginate(list(db.events.values()), limit, offset)
    return ok_array([serializers.event(r) for r in window], limit, offset, total)


@bp.get("/events/<event_id>")
def get_event_route(event_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_event(event_id)
    return ok_object(serializers.event(rec))


@bp.post("/events/<event_id>/cancel")
def cancel_event(event_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_event(event_id)
    if rec["status"] != "SCHEDULED":
        raise err(errors.ERR_EVENT_NOT_SCHEDULED, "Event is not SCHEDULED")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    # Wide cascade across this event's bookings (§3.3).
    for b in list(db.bookings.values()):
        if b["event_id"] != rec["id"]:
            continue
        if b["status"] == "RESERVED":
            # Full fee refund.
            b["status"] = "CANCELLED"
            b["fee_refunded_cents"] = b["reservation_fee_cents"]
            db.touch(b)
        elif b["status"] == "ARRIVED":
            # No refund; void any OPEN order under it (transitive cascade).
            b["status"] = "CANCELLED"
            db.touch(b)
            for o in list(db.orders.values()):
                if o["booking_id"] == b["id"] and o["lifecycle_status"] == "OPEN":
                    services.void_order(o)
    return ok_object(serializers.event(rec))


@bp.get("/events/<event_id>/sales-report")
def sales_report(event_id):
    user_id, role = require_user_context()
    require_role(role, REPORT_ROLES)
    event = get_event(event_id)

    booking_ids = {b["id"] for b in db.bookings.values() if b["event_id"] == event["id"]}

    settled_orders = [
        o for o in db.orders.values()
        if o["booking_id"] in booking_ids and o["lifecycle_status"] == "SETTLED"
    ]

    gross_sales_cents = sum(o["settled_total_cents"] for o in settled_orders)
    order_count = len(settled_orders)
    total_tips_cents = sum(o["tip_cents"] for o in settled_orders)

    net_reservation_cents = 0
    for b in db.bookings.values():
        if b["event_id"] != event["id"]:
            continue
        if b["status"] in ("ARRIVED", "DEPARTED", "NO_SHOW"):
            net_reservation_cents += b["reservation_fee_cents"] - b["fee_refunded_cents"]

    # Per-truck breakdown.
    per_truck = {}
    for o in settled_orders:
        tid = o["truck_id"]
        if tid not in per_truck:
            per_truck[tid] = {"truck_id": tid, "gross_sales_cents": 0, "order_count": 0}
        per_truck[tid]["gross_sales_cents"] += o["settled_total_cents"]
        per_truck[tid]["order_count"] += 1

    def sort_key(entry):
        truck = db.trucks.get(entry["truck_id"])
        created = truck["created_at"] if truck else ""
        seq = truck["_seq"] if truck else 0
        # gross_sales_cents DESC, then created_at ASC (tie-break uses created_at).
        return (-entry["gross_sales_cents"], created, seq)

    truck_breakdown = sorted(per_truck.values(), key=sort_key)

    data = {
        "event_id": event["id"],
        "gross_sales_cents": gross_sales_cents,
        "order_count": order_count,
        "total_tips_cents": total_tips_cents,
        "net_reservation_cents": net_reservation_cents,
        "truck_breakdown": truck_breakdown,
    }
    return ok_object(data)
