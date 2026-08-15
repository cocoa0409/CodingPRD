"""Booking creation/reads/cancel and booking-segment reads."""

from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, check_booking_ownership, require_role
from response import success_list, success_object
from serializers import serialize_booking, serialize_segment
from services.cascades import run_booking_cancel
from services.core import MIN_CONNECT_MINUTES, recompute_refund_credit, stamp_new
from validators import (
    get_json_body,
    get_json_body_optional,
    opt_query_enum,
    pagination_params,
    req_int,
    req_string,
)

bp = Blueprint("bookings", __name__)

CABINS = {"ECONOMY", "PREMIUM", "BUSINESS", "FIRST"}
BOOKING_STATUSES = {"ACTIVE", "DISRUPTED", "REBOOKED", "CANCELLED", "COMPLETED"}
COMPENSATION_STATUSES = {"NONE", "ELIGIBLE_PENDING", "ELECTED_REFUND", "ELECTED_CREDIT", "SETTLED"}
SEGMENT_STATUSES = {"CONFIRMED", "DISRUPTED", "CANCELLED", "REBOOKED", "FLOWN"}
BOOKING_READ_ROLES = ["ReaccommodationAgent", "OpsController", "DutyManager",
                      "FinanceProcessor", "OpsAdmin", "Passenger"]


def _cabin_inventory(flight_id, cabin):
    for ci in db.cabin_inventories.values():
        if ci["flight_id"] == flight_id and ci["cabin"] == cabin:
            return ci
    return None


@bp.post("/irops/bookings")
def create_booking():
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "Passenger"])
    body = get_json_body()
    passenger_id = req_string(body, "passenger_id")
    fare_cents = req_int(body, "fare_cents")
    cabin = body.get("cabin")
    if not isinstance(cabin, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "cabin must be a string")
    if cabin not in CABINS:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "cabin value %r outside declared enum domain" % cabin)
    party_size = req_int(body, "party_size")
    if party_size < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "party_size must be >= 1")
    segments = body.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "segments must be a non-empty array")
    seg_specs = []
    for entry in segments:
        if not isinstance(entry, dict):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "segments entries must be objects")
        flight_id = entry.get("flight_id")
        if not isinstance(flight_id, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "segment flight_id must be a string")
        seq_no = entry.get("seq_no")
        if isinstance(seq_no, bool) or not isinstance(seq_no, int):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "segment seq_no must be an integer")
        seg_specs.append((flight_id, seq_no))
    # passenger ownership: Passenger role may only create bookings for themselves
    if caller.is_passenger and passenger_id != caller.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN_OWNERSHIP,
                           "Passenger may only create bookings for themselves")
    # existence: passenger then flights (left-to-right per resolution order)
    passenger = db.passengers.get(passenger_id)
    if passenger is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Passenger not found")
    flights = []
    for flight_id, _ in seg_specs:
        f = db.flights.get(flight_id)
        if f is None:
            errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
        flights.append(f)
    # business: seat check before connection check
    for f in flights:
        ci = _cabin_inventory(f["id"], cabin)
        avail = (ci["capacity"] - ci["seats_sold"] - ci["interline_seats_committed"]) if ci else 0
        if avail < party_size:
            errors.raise_error(errors.ERR_SEATS_INSUFFICIENT,
                               "seats_available < party_size on a required cabin")
    # connection feasibility on the ordered itinerary (sorted by seq_no)
    ordered = sorted(zip(seg_specs, flights), key=lambda t: t[0][1])
    for i in range(len(ordered) - 1):
        _, f_cur = ordered[i]
        _, f_next = ordered[i + 1]
        if f_cur["sched_arr_utc"] is None or f_next["sched_dep_utc"] is None:
            continue
        gap = (f_next["sched_dep_utc"] - f_cur["sched_arr_utc"]).total_seconds() / 60.0
        if gap < MIN_CONNECT_MINUTES:
            errors.raise_error(errors.ERR_CONNECTION_WINDOW_VIOLATION,
                               "Connection shorter than MIN_CONNECT_MINUTES")
    booking = stamp_new({
        "passenger_id": passenger_id,
        "fare_cents": fare_cents,
        "cabin": cabin,
        "party_size": party_size,
        "booking_status": "ACTIVE",
        "compensation_status": "NONE",
        "eligible_at": None,
        "election_deadline": None,
        "refund_amount_cents": fare_cents,
        "credit_amount_cents": 0,
        "compensation_amount_cents": 0,
        "compensation_basis": None,
    })
    db.bookings[booking["id"]] = booking
    recompute_refund_credit(booking)
    for (flight_id, seq_no), f in zip(seg_specs, flights):
        seg = stamp_new({
            "booking_id": booking["id"],
            "flight_id": flight_id,
            "seq_no": seq_no,
            "cabin": cabin,
            "segment_status": "CONFIRMED",
            "reaccommodation_case_id": None,
        })
        db.booking_segments[seg["id"]] = seg
        ci = _cabin_inventory(flight_id, cabin)
        if ci is not None:
            ci["seats_sold"] += party_size
            from services.core import touch
            touch(ci)
    return success_object(serialize_booking(booking), 201)


@bp.get("/irops/bookings/<bid>")
def get_booking(bid):
    caller = authenticate()
    require_role(caller, BOOKING_READ_ROLES)
    b = db.bookings.get(bid)
    if b is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Booking not found")
    check_booking_ownership(caller, b)
    return success_object(serialize_booking(b), 200)


@bp.get("/irops/bookings")
def list_bookings():
    caller = authenticate()
    require_role(caller, BOOKING_READ_ROLES)
    passenger_id = request.args.get("passenger_id")
    booking_status = opt_query_enum("booking_status", BOOKING_STATUSES)
    compensation_status = opt_query_enum("compensation_status", COMPENSATION_STATUSES)
    if caller.is_passenger:
        if passenger_id is not None and passenger_id != caller.user_id:
            errors.raise_error(errors.ERR_FORBIDDEN_OWNERSHIP,
                               "Passenger may only list their own bookings")
        passenger_id = caller.user_id
    limit, offset = pagination_params()
    items = sorted(db.bookings.values(), key=lambda b: b["created_at"])
    if passenger_id is not None:
        items = [b for b in items if b["passenger_id"] == passenger_id]
    if booking_status is not None:
        items = [b for b in items if b["booking_status"] == booking_status]
    if compensation_status is not None:
        items = [b for b in items if b["compensation_status"] == compensation_status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_booking(b) for b in page], limit, offset, total)


@bp.post("/irops/bookings/<bid>/cancel")
def cancel_booking(bid):
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "Passenger"])
    get_json_body_optional()
    b = db.bookings.get(bid)
    if b is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Booking not found")
    check_booking_ownership(caller, b)
    if b["booking_status"] not in ("ACTIVE", "DISRUPTED", "REBOOKED"):
        errors.raise_error(errors.ERR_INVALID_BOOKING_STATE,
                           "Cannot cancel a booking in state %s" % b["booking_status"])
    run_booking_cancel(b)
    return success_object(serialize_booking(b), 200)


@bp.get("/irops/booking-segments/<sid>")
def get_segment(sid):
    caller = authenticate()
    require_role(caller, BOOKING_READ_ROLES)
    s = db.booking_segments.get(sid)
    if s is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "BookingSegment not found")
    b = db.bookings.get(s["booking_id"])
    if b is not None:
        check_booking_ownership(caller, b)
    return success_object(serialize_segment(s), 200)


@bp.get("/irops/booking-segments")
def list_segments():
    caller = authenticate()
    require_role(caller, BOOKING_READ_ROLES)
    booking_id = request.args.get("booking_id")
    flight_id = request.args.get("flight_id")
    segment_status = opt_query_enum("segment_status", SEGMENT_STATUSES)
    case_id = request.args.get("reaccommodation_case_id")
    limit, offset = pagination_params()
    items = sorted(db.booking_segments.values(), key=lambda s: s["created_at"])
    if booking_id is not None:
        items = [s for s in items if s["booking_id"] == booking_id]
    if flight_id is not None:
        items = [s for s in items if s["flight_id"] == flight_id]
    if segment_status is not None:
        items = [s for s in items if s["segment_status"] == segment_status]
    if case_id is not None:
        items = [s for s in items if s["reaccommodation_case_id"] == case_id]
    if caller.is_passenger:
        items = [s for s in items
                 if db.bookings.get(s["booking_id"]) is not None
                 and db.bookings[s["booking_id"]]["passenger_id"] == caller.user_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_segment(s) for s in page], limit, offset, total)
