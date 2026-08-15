"""DistributionEvent, SortTicket, and PickupAppointment endpoints."""

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import services
from db import clock, _parse_iso
from helpers import (
    get_campaign, get_event, get_order, get_sort_ticket, get_appointment,
    new_id, now_iso, paginate, sort_created,
    req_string, req_int, req_datetime, req_enum,
    serialize_event, serialize_sort_ticket, serialize_appointment,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("distribution", __name__)

EVENT_ALLOWED_CAMPAIGN_STATUSES = (
    "SUPPLIER_ORDERED", "DELIVERED", "SORTED", "DISTRIBUTION_COMPLETE", "RECONCILED",
)


# ---------------------------------------------------------------------------
# Distribution events
# ---------------------------------------------------------------------------

@bp.post("/fundraiser/distribution-events")
def create_event():
    middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    campaign_id = req_string(body, "campaign_id")
    venue = req_string(body, "venue")
    ws = req_datetime(body, "window_start")
    we = req_datetime(body, "window_end")
    capacity = req_int(body, "slot_capacity", minimum=1)
    campaign = get_campaign(campaign_id)
    if not (we > ws):
        raise errors.err_validation("window_end must be strictly later than window_start")
    if campaign["status"] not in EVENT_ALLOWED_CAMPAIGN_STATUSES:
        raise errors.err_invalid_state("Campaign state does not permit scheduling a distribution event")
    # Half-open venue overlap check over SCHEDULED events for (campaign, venue)
    for e in db.distribution_events.values():
        if e["campaign_id"] == campaign_id and e["venue"] == venue and e["status"] == "SCHEDULED":
            ews = _parse_iso(e["window_start"])
            ewe = _parse_iso(e["window_end"])
            if ws < ewe and ews < we:
                raise errors.err_venue_overlap()
    eid = new_id()
    event = {
        "id": eid,
        "campaign_id": campaign_id,
        "venue": venue,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "slot_capacity": capacity,
        "status": "SCHEDULED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.distribution_events[eid] = event
    return success_object(serialize_event(event), status=201)


@bp.get("/fundraiser/distribution-events/<eid>")
def read_event(eid):
    middleware.any_role()
    event = get_event(eid)
    return success_object(serialize_event(event))


@bp.post("/fundraiser/distribution-events/<eid>/complete")
def complete_event(eid):
    middleware.require_role("GroupCoordinator")
    event = get_event(eid)
    get_body()
    if event["status"] != "SCHEDULED":
        raise errors.err_invalid_state("Event is not SCHEDULED")
    if not (clock.now() >= _parse_iso(event["window_start"])):
        raise errors.err_event_not_started()
    event["status"] = "COMPLETED"
    helpers.touch(event)
    return success_object(serialize_event(event))


@bp.post("/fundraiser/distribution-events/<eid>/cancel")
def cancel_event(eid):
    middleware.require_role("GroupCoordinator")
    event = get_event(eid)
    get_body()
    if event["status"] != "SCHEDULED":
        raise errors.err_invalid_state("Event is not SCHEDULED")
    event["status"] = "CANCELLED"
    helpers.touch(event)
    for a in db.pickup_appointments.values():
        if a["distribution_event_id"] == eid and a["status"] == "BOOKED":
            a["status"] = "CANCELLED"
            helpers.touch(a)
    return success_object(serialize_event(event))


# ---------------------------------------------------------------------------
# Sort tickets
# ---------------------------------------------------------------------------

@bp.post("/fundraiser/campaigns/<cid>/generate-sort-tickets")
def generate_sort_tickets(cid):
    middleware.require_role("GroupCoordinator")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "DELIVERED":
        raise errors.err_invalid_state("Campaign is not DELIVERED")
    existing = [t for t in db.sort_tickets.values() if t["campaign_id"] == cid]
    if existing:
        raise errors.err_sort_tickets_already_generated()
    # Earliest SCHEDULED event by (window_start ASC, created_at ASC)
    scheduled = [e for e in db.distribution_events.values()
                 if e["campaign_id"] == cid and e["status"] == "SCHEDULED"]
    earliest_event_id = None
    if scheduled:
        scheduled.sort(key=lambda e: (e["window_start"], e["created_at"]))
        earliest_event_id = scheduled[0]["id"]
    # Aggregate sold units per (seller, product) over non-cancelled orders
    agg = {}
    for o in db.orders.values():
        if o["campaign_id"] != cid or o["status"] == "CANCELLED":
            continue
        for ln in db.order_lines.values():
            if ln["order_id"] == o["id"]:
                key = (o["seller_id"], ln["product_id"])
                agg[key] = agg.get(key, 0) + ln["quantity"]
    ticket_ids = []
    for (seller_id, product_id) in sorted(agg.keys()):
        expected = agg[(seller_id, product_id)]
        if expected <= 0:
            continue
        tid = new_id()
        ticket = {
            "id": tid,
            "campaign_id": cid,
            "seller_id": seller_id,
            "product_id": product_id,
            "distribution_event_id": earliest_event_id,
            "expected_qty": expected,
            "verified_qty": None,
            "status": "PENDING",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
        }
        db.sort_tickets[tid] = ticket
        ticket_ids.append(tid)
    return success_object({"created_count": len(ticket_ids), "ticket_ids": ticket_ids}, status=201)


@bp.get("/fundraiser/sort-tickets")
def list_sort_tickets():
    middleware.any_role()
    limit, offset = parse_pagination()
    items = list(db.sort_tickets.values())
    for param in ("campaign_id", "seller_id", "product_id", "distribution_event_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t.get(param) == v]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_sort_ticket(t) for t in page], limit, offset, total)


@bp.get("/fundraiser/sort-tickets/<tid>")
def read_sort_ticket(tid):
    middleware.any_role()
    ticket = get_sort_ticket(tid)
    return success_object(serialize_sort_ticket(ticket))


@bp.post("/fundraiser/sort-tickets/<tid>/verify")
def verify_sort_ticket(tid):
    user_id, _role = middleware.require_role("GroupCoordinator")
    ticket = get_sort_ticket(tid)
    body = get_body(required=True)
    verified_qty = req_int(body, "verified_qty", minimum=0)
    if ticket["status"] != "PENDING":
        raise errors.err_invalid_state("Sort ticket is not PENDING")
    if verified_qty > ticket["expected_qty"]:
        raise errors.err_quantity_invalid("verified_qty exceeds expected_qty")
    ticket["verified_qty"] = verified_qty
    if verified_qty == ticket["expected_qty"]:
        ticket["status"] = "VERIFIED"
        helpers.touch(ticket)
        return success_object(serialize_sort_ticket(ticket))

    # SHORT cascade
    ticket["status"] = "SHORT"
    helpers.touch(ticket)
    gap = ticket["expected_qty"] - verified_qty
    product = db.products[ticket["product_id"]]
    product["surplus_units"] -= gap
    product["lost_units"] += gap
    helpers.touch(product)

    # Allocate gap to the seller's non-cancelled order lines for this product:
    # greatest submitted_at first, tie by greatest line quantity.
    candidate_lines = []
    for o in db.orders.values():
        if o["campaign_id"] == ticket["campaign_id"] and o["seller_id"] == ticket["seller_id"] and o["status"] != "CANCELLED":
            for ln in db.order_lines.values():
                if ln["order_id"] == o["id"] and ln["product_id"] == ticket["product_id"]:
                    candidate_lines.append((o, ln))
    if candidate_lines:
        candidate_lines.sort(key=lambda pair: (pair[0]["submitted_at"] or "", pair[1]["quantity"]), reverse=True)
        target_line = candidate_lines[0][1]
        target_line["sort_shortage_qty"] += gap
        helpers.touch(target_line)
        # Auto-create a MISSING reconciliation claim on that line
        claim_id = new_id()
        db.claims[claim_id] = {
            "id": claim_id,
            "order_id": target_line["order_id"],
            "order_line_id": target_line["id"],
            "campaign_id": ticket["campaign_id"],
            "claim_type": "MISSING",
            "quantity": gap,
            "note": None,
            "status": "SUBMITTED",
            "reported_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "resolution": None,
            "credit_cents": 0,
            "supersedes_claim_id": None,
            "auto_generated": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
        }
    return success_object(serialize_sort_ticket(ticket))


# ---------------------------------------------------------------------------
# Pickup appointments
# ---------------------------------------------------------------------------

@bp.post("/fundraiser/pickup-appointments")
def book_appointment():
    middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    event_id = req_string(body, "distribution_event_id")
    order_id = req_string(body, "order_id")
    ss = req_datetime(body, "slot_start")
    se = req_datetime(body, "slot_end")
    event = get_event(event_id)
    order = get_order(order_id)
    if event["status"] != "SCHEDULED":
        raise errors.err_invalid_state("Event is not SCHEDULED")
    if order["fulfillment_status"] != "SORTED":
        raise errors.err_invalid_state("Order fulfillment is not SORTED")
    if order["campaign_id"] != event["campaign_id"]:
        raise errors.err_cross_campaign_reference()
    ews = _parse_iso(event["window_start"])
    ewe = _parse_iso(event["window_end"])
    if not (ss >= ews and se > ss and se <= ewe):
        raise errors.err_appointment_window_outside()
    # Capacity: count concurrent overlapping BOOKED appointments at any instant.
    # With half-open intervals, max concurrency occurs at some slot_start; check
    # overlap counts at the new booking's start and at each existing start that
    # falls within the new slot.
    booked = [a for a in db.pickup_appointments.values()
              if a["distribution_event_id"] == event_id and a["status"] == "BOOKED"]

    def overlaps(a_start, a_end, b_start, b_end):
        return a_start < b_end and b_start < a_end

    checkpoints = {ss}
    for a in booked:
        a_start = _parse_iso(a["slot_start"])
        if ss <= a_start < se:
            checkpoints.add(a_start)
    for t in checkpoints:
        concurrent = 1  # the new booking
        for a in booked:
            a_start = _parse_iso(a["slot_start"])
            a_end = _parse_iso(a["slot_end"])
            if a_start <= t < a_end:
                concurrent += 1
        if concurrent > event["slot_capacity"]:
            raise errors.err_slot_capacity_exceeded()

    aid = new_id()
    appt = {
        "id": aid,
        "distribution_event_id": event_id,
        "order_id": order_id,
        "slot_start": body["slot_start"],
        "slot_end": body["slot_end"],
        "status": "BOOKED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.pickup_appointments[aid] = appt
    return success_object(serialize_appointment(appt), status=201)


@bp.get("/fundraiser/pickup-appointments")
def list_appointments():
    middleware.any_role()
    limit, offset = parse_pagination()
    items = list(db.pickup_appointments.values())
    for param in ("distribution_event_id", "order_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_appointment(a) for a in page], limit, offset, total)


@bp.get("/fundraiser/pickup-appointments/<aid>")
def read_appointment(aid):
    middleware.any_role()
    appt = get_appointment(aid)
    return success_object(serialize_appointment(appt))


@bp.post("/fundraiser/pickup-appointments/<aid>/complete")
def complete_appointment(aid):
    middleware.require_role("GroupCoordinator")
    appt = get_appointment(aid)
    body = get_body(required=True)
    outcome = req_enum(body, "outcome", ("COMPLETED", "NO_SHOW"))
    if appt["status"] != "BOOKED":
        raise errors.err_invalid_state("Appointment is not BOOKED")
    appt["status"] = outcome
    helpers.touch(appt)
    return success_object(serialize_appointment(appt))


@bp.post("/fundraiser/pickup-appointments/<aid>/cancel")
def cancel_appointment(aid):
    middleware.require_role("GroupCoordinator")
    appt = get_appointment(aid)
    get_body()
    if appt["status"] != "BOOKED":
        raise errors.err_invalid_state("Appointment is not BOOKED")
    appt["status"] = "CANCELLED"
    helpers.touch(appt)
    return success_object(serialize_appointment(appt))
