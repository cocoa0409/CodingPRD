"""Legs, tickets (+scan), baggage, accessibility requests (+grant/deny),
settlement notes (PRD 3.9, 3.11, 3.12)."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import auth
from helpers import parse_pagination, paginate, get_json_body
from constants import ACCOMMODATIONS, ACCESSIBLE_SLOTS_PER_SERVICE_DATE
import serializers as ser
from services import pricing

bp = Blueprint("misc", __name__)


# ---------------------------------------------------------------------------
# BookingLeg (read/list)
# ---------------------------------------------------------------------------
@bp.route("/v1/legs", methods=["GET"])
def list_legs():
    auth({"Passenger", "SupportAgent", "GateAgent"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    service_date_id = request.args.get("service_date_id")
    fare_class_id = request.args.get("fare_class_id")
    recs = []
    for r in db.booking_legs.values():
        if booking_id is not None and r["booking_id"] != booking_id:
            continue
        if service_date_id is not None and r["service_date_id"] != service_date_id:
            continue
        if fare_class_id is not None and r["fare_class_id"] != fare_class_id:
            continue
        recs.append(r)
    page, meta = paginate(recs, limit, offset)
    return success([ser.booking_leg_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/legs/<booking_leg_id>", methods=["GET"])
def get_leg(booking_leg_id):
    auth({"Passenger", "SupportAgent", "GateAgent"})
    rec = db.booking_legs.get(booking_leg_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "booking leg not found")
    return success(ser.booking_leg_out(rec), 200)


# ---------------------------------------------------------------------------
# Ticket (read/list/scan) — PRD 3.9
# ---------------------------------------------------------------------------
@bp.route("/v1/tickets", methods=["GET"])
def list_tickets():
    auth({"Passenger", "SupportAgent", "GateAgent"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    booking_leg_id = request.args.get("booking_leg_id")
    recs = []
    for r in db.tickets.values():
        if booking_id is not None and r["booking_id"] != booking_id:
            continue
        if booking_leg_id is not None and r["booking_leg_id"] != booking_leg_id:
            continue
        recs.append(r)
    page, meta = paginate(recs, limit, offset)
    return success([ser.ticket_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    auth({"Passenger", "SupportAgent", "GateAgent"})
    rec = db.tickets.get(ticket_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "ticket not found")
    return success(ser.ticket_out(rec), 200)


@bp.route("/v1/tickets/<ticket_id>/scan", methods=["POST"])
def scan_ticket(ticket_id):
    auth({"GateAgent"})
    rec = db.tickets.get(ticket_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "ticket not found")
    # Priority 6: generic state.
    if rec["state"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "ticket not ISSUED")
    # Priority 7: service date lifecycle must be SCHEDULED/DELAYED/DEPARTED.
    leg = db.booking_legs.get(rec["booking_leg_id"])
    sd = db.service_dates.get(leg["service_date_id"]) if leg else None
    if sd is None or sd["lifecycle"] not in ("SCHEDULED", "DELAYED", "DEPARTED"):
        raise err("ERR_PRECONDITION_NOT_MET", "service date lifecycle blocks scanning")
    rec["state"] = "SCANNED"
    db.touch(rec)
    return success(ser.ticket_out(rec), 200)


# ---------------------------------------------------------------------------
# Baggage — PRD 3.11
# ---------------------------------------------------------------------------
@bp.route("/v1/bookings/<booking_id>/baggage", methods=["POST"])
def add_baggage(booking_id):
    user_id, role = auth({"Passenger", "SupportAgent"})
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err("ERR_NOT_FOUND", "booking not found")
    # Priority 4: ownership (Passenger only).
    if role == "Passenger" and user_id != booking["passenger_id"]:
        raise err("ERR_NOT_OWNER", "passenger does not own this booking")

    body = get_json_body()
    weight = body.get("weight_kg")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
        raise err("ERR_INVALID_REQUEST", "weight_kg must be a number > 0")

    fee = pricing.baggage_fee_cents(weight)
    bid = db.new_id()
    rec = {
        "id": bid, "booking_id": booking_id, "weight_kg": weight, "fee_cents": fee,
    }
    db.stamp_create(rec)
    db.baggage_items[bid] = rec
    return success(ser.baggage_out(rec), 201)


@bp.route("/v1/baggage", methods=["GET"])
def list_baggage():
    auth({"Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    recs = [r for r in db.baggage_items.values()
            if booking_id is None or r["booking_id"] == booking_id]
    page, meta = paginate(recs, limit, offset)
    return success([ser.baggage_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/baggage/<baggage_item_id>", methods=["GET"])
def get_baggage(baggage_item_id):
    auth({"Passenger", "SupportAgent"})
    rec = db.baggage_items.get(baggage_item_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "baggage item not found")
    return success(ser.baggage_out(rec), 200)


# ---------------------------------------------------------------------------
# Accessibility requests — PRD 3.12
# ---------------------------------------------------------------------------
@bp.route("/v1/legs/<booking_leg_id>/accessibility-requests", methods=["POST"])
def create_accessibility_request(booking_leg_id):
    user_id, role = auth({"Passenger", "SupportAgent"})
    leg = db.booking_legs.get(booking_leg_id)
    if leg is None:
        raise err("ERR_NOT_FOUND", "booking leg not found")
    # Priority 4: ownership (Passenger owns the booking the leg belongs to).
    if role == "Passenger":
        booking = db.bookings.get(leg["booking_id"])
        if booking is None or user_id != booking["passenger_id"]:
            raise err("ERR_NOT_OWNER", "passenger does not own this leg")

    body = get_json_body()
    accommodation = body.get("accommodation")
    if accommodation not in ACCOMMODATIONS:
        raise err("ERR_INVALID_REQUEST", "accommodation must be a valid kind")

    aid = db.new_id()
    rec = {
        "id": aid, "booking_leg_id": booking_leg_id,
        "accommodation": accommodation, "status": "REQUESTED",
    }
    db.stamp_create(rec)
    db.accessibility_requests[aid] = rec
    return success(ser.accessibility_out(rec), 201)


@bp.route("/v1/accessibility-requests", methods=["GET"])
def list_accessibility_requests():
    auth({"Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    booking_leg_id = request.args.get("booking_leg_id")
    recs = [r for r in db.accessibility_requests.values()
            if booking_leg_id is None or r["booking_leg_id"] == booking_leg_id]
    page, meta = paginate(recs, limit, offset)
    return success([ser.accessibility_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/accessibility-requests/<accessibility_request_id>", methods=["GET"])
def get_accessibility_request(accessibility_request_id):
    auth({"Passenger", "SupportAgent"})
    rec = db.accessibility_requests.get(accessibility_request_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "accessibility request not found")
    return success(ser.accessibility_out(rec), 200)


def _service_date_of_request(rec):
    leg = db.booking_legs.get(rec["booking_leg_id"])
    if leg is None:
        return None
    return db.service_dates.get(leg["service_date_id"])


@bp.route("/v1/accessibility-requests/<accessibility_request_id>/grant", methods=["POST"])
def grant_accessibility_request(accessibility_request_id):
    auth({"SupportAgent"})
    rec = db.accessibility_requests.get(accessibility_request_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "accessibility request not found")
    # Priority 6: generic state.
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "request not REQUESTED")
    # Priority 10: accessible-slot ceiling on the leg's service date.
    sd = _service_date_of_request(rec)
    if sd is not None:
        granted = 0
        for other in db.accessibility_requests.values():
            if other["status"] != "GRANTED":
                continue
            other_sd = _service_date_of_request(other)
            if other_sd is not None and other_sd["id"] == sd["id"]:
                granted += 1
        if granted + 1 > ACCESSIBLE_SLOTS_PER_SERVICE_DATE:
            raise err("ERR_ACCESSIBILITY_UNAVAILABLE", "no accessible slots remain")
    rec["status"] = "GRANTED"
    db.touch(rec)
    return success(ser.accessibility_out(rec), 200)


@bp.route("/v1/accessibility-requests/<accessibility_request_id>/deny", methods=["POST"])
def deny_accessibility_request(accessibility_request_id):
    auth({"SupportAgent"})
    rec = db.accessibility_requests.get(accessibility_request_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "accessibility request not found")
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "request not REQUESTED")
    rec["status"] = "DENIED"
    db.touch(rec)
    return success(ser.accessibility_out(rec), 200)


# ---------------------------------------------------------------------------
# Settlement notes (read/list) — PRD 3.6
# ---------------------------------------------------------------------------
@bp.route("/v1/settlement-notes", methods=["GET"])
def list_settlement_notes():
    auth({"Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    recs = [r for r in db.settlement_notes.values()
            if booking_id is None or r["booking_id"] == booking_id]
    page, meta = paginate(recs, limit, offset)
    return success([ser.settlement_note_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/settlement-notes/<settlement_note_id>", methods=["GET"])
def get_settlement_note(settlement_note_id):
    auth({"Passenger", "SupportAgent"})
    rec = db.settlement_notes.get(settlement_note_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "settlement note not found")
    return success(ser.settlement_note_out(rec), 200)
