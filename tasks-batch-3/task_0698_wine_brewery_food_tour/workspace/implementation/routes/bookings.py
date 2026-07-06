"""Booking endpoints, lifecycle, and the seat pool (PRD §3.6, §3.7).

Booking has parallel dimensions: lifecycle (status) and payment (payment_status).
"""
from flask import Blueprint, request
import errors
import validate
import serialize
from db import db
from clock import clock
from middleware import require_auth
from records import new_record, touch
from response import object_response, array_response
from util import parse_datetime
from services import pricing
from services import departures as departure_svc

bp = Blueprint("bookings", __name__)

READ_ROLES = {"Operator", "Guide", "Guest"}
NON_TERMINAL = ("DRAFT", "RESERVED", "PAID", "CHECKED_IN")


def _quote_for(booking):
    """Compute and store subtotal/gratuity/total on a booking from current
    related state (departure, tour product, optional add-on)."""
    departure = db.departures[booking["departure_id"]]
    product = db.tour_products[departure["tour_product_id"]]
    addon_price = None
    if booking.get("add_on_id"):
        addon = db.add_ons[booking["add_on_id"]]
        addon_price = addon["price_per_person_cents"]
    q = pricing.quote(
        base_price_per_person_cents=product["base_price_per_person_cents"],
        party_size=booking["party_size"],
        addon_price_per_person_cents=addon_price,
        is_charter=departure["is_private_charter"],
        charter_fee_cents=product["charter_fee_cents"],
        gratuity_pct=product["gratuity_pct"],
    )
    booking["subtotal_cents"] = q["subtotal_cents"]
    booking["gratuity_cents"] = q["gratuity_cents"]
    booking["total_cents"] = q["total_cents"]


def _age_at(birth_date_str, at_dt):
    bd = parse_datetime(birth_date_str)
    years = at_dt.year - bd.year
    if (at_dt.month, at_dt.day) < (bd.month, bd.day):
        years -= 1
    return years


@bp.post("/bookings")
def create():
    require_auth({"Operator", "Guest"})
    body = validate.get_json_body()
    validate.require_fields(body, ["departure_id", "lead_guest_id", "pickup_point_id", "party_size"])
    departure_id = body["departure_id"]
    lead_guest_id = body["lead_guest_id"]
    pickup_point_id = body["pickup_point_id"]
    for fk in (departure_id, lead_guest_id, pickup_point_id):
        if not isinstance(fk, str):
            raise errors.err(errors.ERR_INVALID_REQUEST, "FK fields must be strings")

    add_on_id = body.get("add_on_id")
    if add_on_id is not None and not isinstance(add_on_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "add_on_id must be a string")

    # FK existence (priority 4)
    if departure_id not in db.departures:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "departure_id references a non-existent departure")
    if lead_guest_id not in db.guests:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "lead_guest_id references a non-existent guest")
    if pickup_point_id not in db.pickup_points:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "pickup_point_id references a non-existent pickup point")
    if add_on_id is not None and add_on_id not in db.add_ons:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "add_on_id references a non-existent add-on")

    party_size = validate.require_int(body, "party_size")
    # range check (priority 7): party_size > 0
    if party_size <= 0:
        validate.out_of_range()

    rec = new_record({
        "departure_id": departure_id,
        "lead_guest_id": lead_guest_id,
        "pickup_point_id": pickup_point_id,
        "party_size": party_size,
        "add_on_id": add_on_id,
        "subtotal_cents": 0,
        "gratuity_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "refund_cents": 0,
        "status": "DRAFT",
        "payment_status": "UNPAID",
    })
    _quote_for(rec)
    db.bookings[rec["id"]] = rec
    return object_response(serialize.booking(rec), status=201)


@bp.get("/bookings")
def list_bookings():
    require_auth(READ_ROLES)
    limit, offset = validate.parse_pagination()
    departure_id = request.args.get("departure_id")
    lead_guest_id = request.args.get("lead_guest_id")
    pickup_point_id = request.args.get("pickup_point_id")
    add_on_id = request.args.get("add_on_id")
    status = request.args.get("status")
    records = list(db.bookings.values())
    if departure_id is not None:
        records = [r for r in records if r["departure_id"] == departure_id]
    if lead_guest_id is not None:
        records = [r for r in records if r["lead_guest_id"] == lead_guest_id]
    if pickup_point_id is not None:
        records = [r for r in records if r["pickup_point_id"] == pickup_point_id]
    if add_on_id is not None:
        records = [r for r in records if r.get("add_on_id") == add_on_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, total = validate.paginate(records, limit, offset, serialize.booking)
    return array_response(items, limit, offset, total)


@bp.get("/bookings/<bid>")
def get_booking(bid):
    require_auth(READ_ROLES)
    rec = db.bookings.get(bid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Booking not found")
    return object_response(serialize.booking(rec), status=200)


@bp.post("/bookings/<bid>/reserve")
def reserve(bid):
    require_auth({"Operator", "Guest"})
    booking = db.bookings.get(bid)
    if booking is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Booking not found")

    body = validate.get_json_body()
    # expected_departure_version is a non-optional field (PRD §2.7)
    validate.require_fields(body, ["expected_departure_version"])
    expected_version = validate.require_int(body, "expected_departure_version")

    # booking must be DRAFT (state-machine precondition, priority 8)
    if booking["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT booking can be reserved")

    departure = db.departures[booking["departure_id"]]
    product = db.tour_products[departure["tour_product_id"]]
    guest = db.guests[booking["lead_guest_id"]]

    # recompute the quote at reserve time (PRD §3.6)
    _quote_for(booking)

    # deterministic reserve-time check order (PRD §3.6):
    # 1) departure SCHEDULED
    if departure["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_DEPARTURE_NOT_BOOKABLE, "Departure is not bookable")

    # 2) underage lead guest
    age = _age_at(guest["birth_date"], clock.now())
    if age < product["min_guest_age"]:
        raise errors.err(errors.ERR_UNDERAGE_GUEST, "Lead guest is below the minimum age")

    seats_taken = departure_svc.compute_seats_taken(departure["id"])

    # 3) private charter whole-van rule
    if departure["is_private_charter"]:
        other_non_terminal = any(
            b["id"] != booking["id"]
            and b["departure_id"] == departure["id"]
            and b["status"] in NON_TERMINAL
            for b in db.bookings.values())
        if booking["party_size"] != departure["seat_capacity"] or other_non_terminal:
            raise errors.err(errors.ERR_CHARTER_WHOLE_VAN_REQUIRED,
                             "Charter booking must take the whole van and be the sole booking")

    # 4) seat capacity
    if seats_taken + booking["party_size"] > departure["seat_capacity"]:
        raise errors.err(errors.ERR_SEAT_CAPACITY_EXCEEDED, "Reservation exceeds seat capacity")

    # 5) OCC stale version
    if expected_version != departure["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Departure version is stale")

    # commit: advance booking, sync departure ledger + version
    booking["status"] = "RESERVED"
    touch(booking)
    # seats_taken / expected_headcount are derived on read; bump departure
    # version to reflect the seat-pool mutation (PRD §3.6 / §2.7).
    touch(departure)
    return object_response(serialize.booking(booking), status=200)


@bp.post("/bookings/<bid>/pay")
def pay(bid):
    require_auth({"Operator", "Guest"})
    booking = db.bookings.get(bid)
    if booking is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Booking not found")
    if booking["status"] != "RESERVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a RESERVED booking can be paid")
    if booking["payment_status"] != "UNPAID":
        raise errors.err(errors.ERR_INVALID_STATE, "Booking is not UNPAID")

    guest = db.guests[booking["lead_guest_id"]]
    if not (guest["age_verified"] and guest["waiver_signed"]):
        raise errors.err(errors.ERR_GUEST_NOT_CLEARED,
                         "Lead guest must be age-verified and waiver-signed")

    booking["payment_status"] = "CAPTURED"
    booking["amount_paid_cents"] = booking["total_cents"]
    booking["status"] = "PAID"
    touch(booking)
    return object_response(serialize.booking(booking), status=200)


@bp.post("/bookings/<bid>/check-in")
def check_in(bid):
    require_auth({"Guide"})
    booking = db.bookings.get(bid)
    if booking is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Booking not found")
    if booking["status"] != "PAID":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PAID booking can be checked in")

    departure = db.departures[booking["departure_id"]]
    if departure["status"] != "DEPARTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Departure is not DEPARTED")

    guest = db.guests[booking["lead_guest_id"]]
    if not guest["age_verified"]:
        raise errors.err(errors.ERR_GUEST_NOT_CLEARED, "Lead guest must be age-verified")

    booking["status"] = "CHECKED_IN"
    touch(booking)
    return object_response(serialize.booking(booking), status=200)


@bp.post("/bookings/<bid>/cancel")
def cancel(bid):
    require_auth({"Operator", "Guest"})
    booking = db.bookings.get(bid)
    if booking is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Booking not found")
    if booking["status"] not in ("DRAFT", "RESERVED", "PAID"):
        raise errors.err(errors.ERR_INVALID_STATE, "Booking cannot be cancelled from its current state")

    prev_status = booking["status"]
    departure = db.departures[booking["departure_id"]]

    if prev_status == "PAID":
        # compute refund over amount_paid_cents at lead time vs depart_at
        depart_at = parse_datetime(departure["depart_at"])
        hb = pricing.hours_before(depart_at, clock.now())
        booking["refund_cents"] = pricing.refund(
            booking["amount_paid_cents"], hb, weather_override=False)
        if booking["refund_cents"] > 0 and booking["payment_status"] == "CAPTURED":
            booking["payment_status"] = "REFUNDED"

    booking["status"] = "CANCELLED"
    touch(booking)

    # seat pool restored if it had consumed seats (RESERVED / PAID): the derived
    # seats_taken/expected_headcount drop automatically; bump departure version.
    if prev_status in ("RESERVED", "PAID"):
        touch(departure)

    return object_response(serialize.booking(booking), status=200)
