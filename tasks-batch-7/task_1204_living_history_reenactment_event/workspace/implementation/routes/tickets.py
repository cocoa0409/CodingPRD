"""Ticket order and parking pass endpoints."""

from flask import Blueprint, request

import db
import serializers
from errors import fail
from middleware import authenticate, get_event, get_order, get_pass, own_order_scope
from response import success
from services import cascades, derived
from services.common import new_record, paginate, touch
from services.derived import sorted_all
from services.pricing import parking_units_used, refund_amounts, ticket_total_cents
from services.pricing import LINE_TYPES
from util import body, is_int, req_enum, req_str

bp = Blueprint("tickets", __name__)

ORDER_STATUSES = ("RESERVED", "PAID", "CHECKED_IN", "REFUNDED", "CANCELLED")


def _validate_lines(data):
    lines = data.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        fail("ERR_VALIDATION", "lines must be a non-empty array")
    out = []
    for line in lines:
        if not isinstance(line, dict):
            fail("ERR_VALIDATION", "each line must be an object")
        lt = line.get("line_type")
        if lt not in LINE_TYPES:
            fail("ERR_VALIDATION", "unknown line_type")
        qty = line.get("quantity")
        if not is_int(qty) or qty < 1:
            fail("ERR_VALIDATION", "quantity must be an integer >= 1")
        out.append({"line_type": lt, "quantity": qty})
    return out


@bp.post("/events/<event_id>/ticket-orders")
def create_ticket_order(event_id):
    uid, _ = authenticate(["Spectator"], creation=True)
    ev = get_event(event_id)
    if ev["event_posture"] not in ("PUBLISHED", "EVENT_OPEN"):
        fail("ERR_INVALID_EVENT_POSTURE", "ticket sales require PUBLISHED or EVENT_OPEN")
    data = body(request)
    buyer_name = req_str(data, "buyer_name")
    lines = _validate_lines(data)
    rec = new_record()
    rec.update(
        event_id=ev["id"],
        buyer_user_id=uid,
        buyer_name=buyer_name,
        lines=lines,
        status="RESERVED",
        quoted_total_cents=ticket_total_cents(ev, lines, rec["created_at"]),
        final_total_cents=None,
        refund_amount_cents=None,
        retained_fee_cents=None,
        refund_reason=None,
        paid_at=None,
        refunded_at=None,
    )
    db.orders[rec["id"]] = rec
    return success(serializers.ticket_order(rec), 201)


@bp.get("/events/<event_id>/ticket-orders")
def list_ticket_orders(event_id):
    authenticate(["EventOrganizer"])
    ev = get_event(event_id)
    items = [o for o in db.orders.values() if o["event_id"] == ev["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(sorted_all(items))
    return success([serializers.ticket_order(o) for o in page], 200, pagination=meta)


@bp.get("/ticket-orders/<order_id>")
def read_ticket_order(order_id):
    uid, role = authenticate(["Spectator", "EventOrganizer"])
    o = get_order(order_id)
    if role == "Spectator":
        own_order_scope(uid, o)
    return success(serializers.ticket_order(o), 200)


@bp.post("/ticket-orders/<order_id>/pay")
def pay_ticket_order(order_id):
    uid, _ = authenticate(["Spectator"])
    o = get_order(order_id)
    own_order_scope(uid, o)
    if o["status"] != "RESERVED":
        fail("ERR_INVALID_ORDER_STATUS", "only a RESERVED order can be paid")
    data = body(request)
    req_str(data, "payment_method")
    req_str(data, "payment_reference")
    ev = db.events[o["event_id"]]
    paid_at = db.now()
    o["final_total_cents"] = ticket_total_cents(ev, o["lines"], paid_at)
    o["paid_at"] = paid_at
    o["status"] = "PAID"
    touch(o)
    return success(serializers.ticket_order(o), 200)


@bp.post("/ticket-orders/<order_id>/refund")
def refund_ticket_order(order_id):
    uid, role = authenticate(["Spectator", "EventOrganizer"])
    o = get_order(order_id)
    if role == "Spectator":
        own_order_scope(uid, o)
    if o["status"] != "PAID":
        fail("ERR_INVALID_ORDER_STATUS", "only a PAID order can be refunded")
    reason = req_enum(body(request), "reason", ("PATRON_CHOICE", "EVENT_CONTINGENCY"))
    ev = db.events[o["event_id"]]
    if reason == "PATRON_CHOICE":
        if ev["event_posture"] in ("COMPLETED", "CANCELLED"):
            fail("ERR_INVALID_EVENT_POSTURE", "PATRON_CHOICE refunds are unavailable for a terminal event")
    else:
        if ev["event_posture"] != "CANCELLED":
            fail("ERR_INVALID_EVENT_POSTURE", "EVENT_CONTINGENCY refunds require a CANCELLED event")
    refund, retained = refund_amounts(ev, o, reason)
    o["refund_amount_cents"] = refund
    o["retained_fee_cents"] = retained
    o["refund_reason"] = reason
    o["refunded_at"] = db.now()
    o["status"] = "REFUNDED"
    touch(o)
    for ps in db.passes.values():
        if ps["ticket_order_id"] == o["id"] and ps["status"] == "ACTIVE":
            cascades.void_pass(ps)
    return success(serializers.ticket_order(o), 200)


@bp.post("/ticket-orders/<order_id>/check-in")
def check_in_ticket_order(order_id):
    authenticate(["EventOrganizer"])
    o = get_order(order_id)
    ev = db.events[o["event_id"]]
    if ev["event_posture"] not in ("EVENT_OPEN", "RESTRICTED"):
        fail("ERR_INVALID_EVENT_POSTURE", "gate check-in requires EVENT_OPEN or RESTRICTED")
    if o["status"] != "PAID":
        fail("ERR_INVALID_ORDER_STATUS", "only a PAID order can be checked in")
    o["status"] = "CHECKED_IN"
    touch(o)
    return success(serializers.ticket_order(o), 200)


@bp.post("/ticket-orders/<order_id>/parking-passes")
def issue_parking_pass(order_id):
    uid, _ = authenticate(["Spectator"], creation=True)
    o = get_order(order_id)
    own_order_scope(uid, o)
    data = body(request)
    explicit = None
    if data.get("site_area_id") is not None:
        explicit = db.areas.get(data["site_area_id"])
        if explicit is None or explicit["event_id"] != o["event_id"]:
            fail("ERR_AREA_NOT_FOUND", f"site area {data['site_area_id']} not found")
    if o["status"] != "PAID":
        fail("ERR_INVALID_ORDER_STATUS", "parking passes require a PAID order")
    if explicit is not None and explicit["status"] != "ACTIVE":
        fail("ERR_AREA_NOT_ACTIVE", "the parking lot is not ACTIVE")
    plate = req_str(data, "vehicle_plate")
    vehicle_class = req_enum(data, "vehicle_class", ("STANDARD", "OVERSIZE"))
    needed = parking_units_used(vehicle_class)
    if explicit is not None:
        if explicit["area_kind"] != "PARKING":
            fail("ERR_AREA_KIND_MISMATCH", "the named lot is not a PARKING area")
        if derived.area_allocated_units(explicit) + needed > explicit["capacity_units"]:
            fail("ERR_PARKING_CAPACITY_EXCEEDED", "the named lot lacks capacity")
        lot = explicit
    else:
        # Deterministic selector: remaining capacity DESC, then created_at ASC.
        candidates = []
        for a in db.areas.values():
            if a["event_id"] != o["event_id"] or a["area_kind"] != "PARKING" or a["status"] != "ACTIVE":
                continue
            remaining = a["capacity_units"] - derived.area_allocated_units(a)
            if remaining >= needed:
                candidates.append((remaining, a))
        if not candidates:
            fail("ERR_NO_PARKING_AVAILABLE", "no eligible PARKING area has capacity")
        candidates.sort(key=lambda t: (-t[0], t[1]["created_at"], t[1]["_seq"]))
        lot = candidates[0][1]
    rec = new_record()
    rec.update(
        ticket_order_id=o["id"],
        site_area_id=lot["id"],
        vehicle_plate=plate,
        vehicle_class=vehicle_class,
        units_used=needed,
        status="ACTIVE",
    )
    db.passes[rec["id"]] = rec
    return success(serializers.parking_pass(rec), 201)


@bp.get("/ticket-orders/<order_id>/parking-passes")
def list_order_passes(order_id):
    uid, role = authenticate(["Spectator", "EventOrganizer"])
    o = get_order(order_id)
    if role == "Spectator":
        own_order_scope(uid, o)
    items = sorted_all(p for p in db.passes.values() if p["ticket_order_id"] == o["id"])
    page, meta = paginate(items)
    return success([serializers.parking_pass(p) for p in page], 200, pagination=meta)


@bp.get("/site-areas/<area_id>/parking-passes")
def list_lot_passes(area_id):
    authenticate(["EventOrganizer", "SafetyOfficer"])
    from middleware import get_area

    area = get_area(area_id)
    items = sorted_all(p for p in db.passes.values() if p["site_area_id"] == area["id"])
    page, meta = paginate(items)
    return success([serializers.parking_pass(p) for p in page], 200, pagination=meta)


@bp.post("/parking-passes/<pass_id>/void")
def void_parking_pass(pass_id):
    uid, role = authenticate(["Spectator", "EventOrganizer"])
    ps = get_pass(pass_id)
    if role == "Spectator":
        order = db.orders.get(ps["ticket_order_id"])
        if order is None or order["buyer_user_id"] != uid:
            fail("ERR_FORBIDDEN", "spectator may void only passes on their own orders")
    if ps["status"] != "ACTIVE":
        fail("ERR_INVALID_PASS_STATUS", "only an ACTIVE pass can be voided")
    cascades.void_pass(ps)
    return success(serializers.parking_pass(ps), 200)
