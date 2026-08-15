"""Reservation endpoints (PRD 3.4, 3.5, 3.6, 3.7): booking, confirmation,
check-in settlement, flown/complete, customer cancellation."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_RESERVATION_NOT_OWNED, ERR_PAYLOAD_EXCEEDED, ERR_BASKET_CAPACITY_EXCEEDED,
    ERR_CHARTER_EXCLUSIVE, ERR_MANIFEST_INCOMPLETE, ERR_PAYMENT_AMOUNT_MISMATCH,
)
from middleware import (
    authorized, ALL_READ_ROLES, peek_event_type, check_event_slice,
)
from response import success_object, success_list
from services.calculations import fare_quote
from services.cascades import create_refund
from services.calculations import refund_requested_amount
from services.core import (
    new_record, touch, public_reservation, flight_seats_sold, flight_payload_used,
    sort_created,
)
from util import parse_datetime, CLOCK
from validate import (
    get_body, req_str, req_int, opt_int, opt_enum, require_path_resource,
    get_pagination,
)

bp = Blueprint("reservations", __name__, url_prefix="/v1")

CUSTOMER_EVENTS = {"CONFIRM", "CANCEL"}
OM_EVENTS = {"CHECK_IN", "MARK_FLOWN", "COMPLETE"}
ALL_EVENTS = CUSTOMER_EVENTS | OM_EVENTS
EVENT_SLICES = {"Customer": CUSTOMER_EVENTS, "OperationsManager": OM_EVENTS}

PHOTO_TIERS = ("NONE", "STANDARD", "DELUXE")


# ---------------------------------------------------------------------------
# Booking (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/flights/<flight_id>/reservations")
def create_reservation(flight_id):
    caller = authorized(["Customer"])
    flight = require_path_resource("flights", flight_id, "flight")
    body = get_body()
    customer_id = req_str(body, "customer_id")
    party_size = req_int(body, "party_size", minimum=1)
    declared_weight = req_int(body, "declared_weight_lbs", minimum=0)
    photo_tier = opt_enum(body, "photo_package_tier", PHOTO_TIERS, default="NONE")
    if customer_id not in db["customers"]:
        raise_error(ERR_NOT_FOUND, f"customer not found: {customer_id}")
    # Priority 6: entity-backed ownership — customer_id must equal X-User-ID
    if customer_id != caller.user_id:
        raise_error(ERR_RESERVATION_NOT_OWNED,
                    "customer_id does not match the acting customer's X-User-ID")
    # Priority 7: booking only on a SCHEDULED flight
    if flight["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot book on a flight in {flight['status']}")
    balloon = db["balloons"].get(flight["balloon_id"])
    # Business order (PRD 3.4): weight-and-balance first, then seats
    if balloon is not None:
        if declared_weight + balloon["empty_weight_lbs"] + flight["fuel_lbs"] \
                > balloon["max_gross_weight_lbs"]:
            raise_error(ERR_PAYLOAD_EXCEEDED,
                        "declared weight plus empty weight and fuel exceeds max gross")
        if flight["kind"] == "SHARED":
            if flight_seats_sold(flight["id"]) + party_size > balloon["basket_capacity_passengers"]:
                raise_error(ERR_BASKET_CAPACITY_EXCEEDED,
                            "party size exceeds remaining basket seats")
        else:  # CHARTER: whole-basket exclusive
            has_live = any(
                r["flight_id"] == flight["id"] and r["booking_status"] != "CANCELLED"
                for r in db["reservations"].values())
            if has_live or party_size > balloon["basket_capacity_passengers"]:
                raise_error(ERR_CHARTER_EXCLUSIVE,
                            "charter flights allow exactly one non-cancelled reservation "
                            "within basket capacity")
    quoted = fare_quote(flight, balloon, party_size, declared_weight, photo_tier)
    rec = new_record("reservations", {
        "flight_id": flight["id"],
        "customer_id": customer_id,
        "party_size": party_size,
        "declared_weight_lbs": declared_weight,
        "photo_package_tier": photo_tier,
        "booking_status": "PENDING",
        "payment_status": "UNPAID",
        "quoted_fare_cents": quoted,
        "final_fare_cents": None,
        "paid_cents": 0,
        "refunded_cents": 0,
        "goodwill_credit_cents": 0,
        "cancel_reason": None,
    })
    if photo_tier != "NONE":
        new_record("photo_packages", {
            "reservation_id": rec["id"],
            "tier": photo_tier,
            "photo_count": 0,
            "status": "PENDING",
            "delivered_at": None,
        }, with_version=False)
    return success_object(public_reservation(rec), status=201)


# ---------------------------------------------------------------------------
# List / read
# ---------------------------------------------------------------------------

@bp.get("/reservations")
def list_reservations():
    authorized(ALL_READ_ROLES)
    items = list(db["reservations"].values())
    for field in ("flight_id", "customer_id", "booking_status"):
        value = request.args.get(field)
        if value is not None:
            items = [r for r in items if r.get(field) == value]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_reservation(r) for r in page], total, limit, offset)


@bp.get("/reservations/<reservation_id>")
def get_reservation(reservation_id):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource("reservations", reservation_id, "reservation")
    return success_object(public_reservation(rec))


# ---------------------------------------------------------------------------
# Lifecycle events (PRD 3.4-3.7)
# ---------------------------------------------------------------------------

@bp.post("/reservations/<reservation_id>/events")
def reservation_events(reservation_id):
    caller = authorized(["Customer", "OperationsManager"])
    # Priority 2: event-to-role slice segregation (before existence/body)
    check_event_slice(caller, peek_event_type(), EVENT_SLICES)
    rec = require_path_resource("reservations", reservation_id, "reservation")
    body = get_body()
    event_type = req_str(body, "event_type")
    if event_type not in ALL_EVENTS:
        raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")
    flight = db["flights"].get(rec["flight_id"])

    # ---- Customer events: ownership (priority 6) before state (7) ----
    if event_type in CUSTOMER_EVENTS and rec["customer_id"] != caller.user_id:
        raise_error(ERR_RESERVATION_NOT_OWNED,
                    "acting customer does not match reservation.customer_id")

    if event_type == "CONFIRM":
        paid = req_int(body, "paid_cents", minimum=0)
        if rec["booking_status"] != "PENDING":
            raise_error(ERR_INVALID_STATE,
                        f"cannot CONFIRM from {rec['booking_status']}")
        if flight is None or flight["status"] != "SCHEDULED":
            raise_error(ERR_INVALID_STATE, "flight is no longer SCHEDULED")
        if paid != rec["quoted_fare_cents"]:
            raise_error(ERR_PAYMENT_AMOUNT_MISMATCH,
                        "paid_cents must equal quoted_fare_cents exactly")
        rec["booking_status"] = "CONFIRMED"
        rec["payment_status"] = "PAID"
        rec["paid_cents"] = paid
        touch(rec)
        return success_object(public_reservation(rec))

    if event_type == "CANCEL":
        if rec["booking_status"] not in ("PENDING", "CONFIRMED"):
            raise_error(ERR_INVALID_STATE,
                        f"cannot CANCEL from {rec['booking_status']}")
        if rec["booking_status"] == "PENDING":
            # Nothing paid — no refund, no cancel reason
            rec["booking_status"] = "CANCELLED"
        else:
            # Timing fork: strictly before dawn_window_start - 24h is EARLY
            deadline = parse_datetime(flight["dawn_window_start"]) - timedelta(hours=24)
            if CLOCK.now() < deadline:
                rec["cancel_reason"] = "CUSTOMER_CANCEL_EARLY"
                amount = refund_requested_amount(
                    flight["kind"], rec["paid_cents"], rec["party_size"],
                    "CUSTOMER_CANCEL_EARLY")
                if amount is not None:
                    create_refund(rec, "CUSTOMER_CANCEL_EARLY", amount)
            else:
                # LATE: no refund; fare forfeited; payment_status stays PAID
                rec["cancel_reason"] = "CUSTOMER_CANCEL_LATE"
            rec["booking_status"] = "CANCELLED"
        touch(rec)
        return success_object(public_reservation(rec))

    # ---- OperationsManager events ----
    if event_type == "CHECK_IN":
        additional = opt_int(body, "additional_paid_cents", default=0, minimum=0)
        if rec["booking_status"] != "CONFIRMED":
            raise_error(ERR_INVALID_STATE,
                        f"cannot CHECK_IN from {rec['booking_status']}")
        if flight is None or flight["status"] not in ("WEATHER_REVIEW", "CLEARED_FOR_LAUNCH"):
            raise_error(ERR_INVALID_STATE,
                        "check-in requires the flight to be in WEATHER_REVIEW or "
                        "CLEARED_FOR_LAUNCH")
        balloon = db["balloons"].get(flight["balloon_id"]) if flight else None
        passengers = [p for p in db["passengers"].values()
                      if p["reservation_id"] == rec["id"]]
        party_weight = sum(p["weight_lbs"] for p in passengers)
        # Business order (PRD 3.5): payload, then manifest, then settlement
        if balloon is not None and flight is not None:
            prospective = flight_payload_used(flight) + party_weight
            if prospective > balloon["max_gross_weight_lbs"]:
                raise_error(ERR_PAYLOAD_EXCEEDED,
                            "prospective payload exceeds balloon max gross weight")
        if len(passengers) != rec["party_size"]:
            raise_error(ERR_MANIFEST_INCOMPLETE,
                        "passenger manifest count does not equal party_size")
        final_fare = fare_quote(flight, balloon, rec["party_size"], party_weight,
                                rec["photo_package_tier"])
        delta = final_fare - rec["paid_cents"]
        required_additional = max(0, delta)
        if additional != required_additional:
            raise_error(ERR_PAYMENT_AMOUNT_MISMATCH,
                        "additional_paid_cents must equal the settle delta "
                        f"{required_additional}")
        if delta > 0:
            rec["paid_cents"] += delta
        elif delta < 0:
            customer = db["customers"].get(rec["customer_id"])
            if customer is not None:
                customer["wallet_credit_cents"] += -delta
                touch(customer)
            rec["paid_cents"] += delta
        rec["final_fare_cents"] = final_fare
        rec["booking_status"] = "CHECKED_IN"
        touch(rec)
        return success_object(public_reservation(rec))

    if event_type == "MARK_FLOWN":
        if rec["booking_status"] != "CHECKED_IN":
            raise_error(ERR_INVALID_STATE,
                        f"cannot MARK_FLOWN from {rec['booking_status']}")
        if flight is None or flight["status"] != "LANDED":
            raise_error(ERR_INVALID_STATE, "flight is not LANDED")
        rec["booking_status"] = "FLOWN"
        touch(rec)
        return success_object(public_reservation(rec))

    if event_type == "COMPLETE":
        photo_count = opt_int(body, "photo_count", default=0, minimum=0)
        if rec["booking_status"] != "FLOWN":
            raise_error(ERR_INVALID_STATE,
                        f"cannot COMPLETE from {rec['booking_status']}")
        if flight is None or flight["status"] != "LANDED":
            raise_error(ERR_INVALID_STATE, "flight is not LANDED")
        rec["booking_status"] = "COMPLETED"
        touch(rec)
        for pp in db["photo_packages"].values():
            if pp["reservation_id"] == rec["id"] and pp["status"] == "PENDING":
                pp["status"] = "DELIVERED"
                pp["photo_count"] = photo_count
                pp["delivered_at"] = CLOCK.now_iso()
        return success_object(public_reservation(rec))

    raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")
