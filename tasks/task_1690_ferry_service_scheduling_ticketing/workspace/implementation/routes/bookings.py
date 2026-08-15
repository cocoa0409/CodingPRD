"""Booking endpoints (PRD §3.5, §3.8)."""

from flask import Blueprint, request

from db import db, now_iso
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SAILING_NOT_BOOKABLE,
    ERR_NOT_RESOURCE_OWNER, ERR_INVALID_PARTY_SPEC,
    ERR_FARE_SCHEDULE_NOT_EFFECTIVE, ERR_CAPACITY_EXCEEDED,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import (
    touch, recompute_sailing_counters, booking_fare_quote,
)
from services.fare_schedule import find_effective_schedule
from services.serializers import serialize_booking

bp = Blueprint("bookings", __name__)


def _get_booking(booking_id):
    b = db.bookings.get(booking_id)
    if b is None:
        raise_error(ERR_NOT_FOUND, "Booking not found")
    return b


def _check_owner(user_id, booking):
    """Priority 7: customer may only act on own bookings (X-User-ID == customer_id)."""
    if booking["customer_id"] != user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "Customer may only act on its own bookings")


def _validate_party_spec(passenger_count, has_vehicle, vehicle_length_feet):
    """Priority 11: vehicle_length_feet in [1, 80] when has_vehicle; length
    required iff has_vehicle; malformed combos -> ERR_INVALID_PARTY_SPEC."""
    if has_vehicle:
        if vehicle_length_feet is None:
            raise_error(ERR_INVALID_PARTY_SPEC,
                        "vehicle_length_feet is required when has_vehicle is true")
        length = int(vehicle_length_feet)
        if length < 1 or length > 80:
            raise_error(ERR_INVALID_PARTY_SPEC,
                        "vehicle_length_feet must be between 1 and 80 feet")
    if passenger_count is None or int(passenger_count) < 0:
        raise_error(ERR_INVALID_PARTY_SPEC,
                    "passenger_count must be at least 0")


def _check_capacity(sailing, add_feet, add_pax, exclude_booking_id=None):
    """Priority 14: reservation pool deck feet and passenger capacity.
    reserved_vehicle_feet + requested feet <= reserved_deck_allotment_feet;
    booked_passengers + passenger_count <= vessel passenger_capacity."""
    vessel = db.vessels[sailing["vessel_id"]]
    reserved = 0
    pax = 0
    for b in db.bookings.values():
        if b["sailing_id"] != sailing["id"]:
            continue
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["status"] in ("RESERVED", "CONFIRMED", "MODIFIED", "CHECKED_IN", "BOARDED"):
            if b.get("has_vehicle"):
                reserved += int(b.get("vehicle_length_feet") or 0)
            pax += int(b["passenger_count"])
    for e in db.standby_entries.values():
        if e["sailing_id"] == sailing["id"] and e["status"] == "CLEARED":
            pax += int(e["passenger_count"])
    if reserved + add_feet > int(sailing["reserved_deck_allotment_feet"]):
        raise_error(ERR_CAPACITY_EXCEEDED,
                    "Reservation pool deck capacity would be exceeded")
    if pax + add_pax > int(vessel["passenger_capacity"]):
        raise_error(ERR_CAPACITY_EXCEEDED,
                    "Passenger capacity would be exceeded")


@bp.post("/ferry/sailings/<sailing_id>/bookings")
def create_booking(sailing_id):
    user_id, _role = require_roles("Customer")

    # Priority 3: path id
    sailing = db.sailings.get(sailing_id)
    if sailing is None:
        raise_error(ERR_NOT_FOUND, "Sailing not found")

    payload = request.get_json(silent=True) or {}

    # Priority 7: ownership — customer_id must equal X-User-ID
    customer_id = payload.get("customer_id")
    if customer_id != user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER,
                    "customer_id must equal the acting customer's id")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise_error(ERR_NOT_FOUND, "Customer not found")

    # Priority 5: sailing posture
    if sailing["status"] != "OPEN_FOR_BOOKING":
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Sailing is not OPEN_FOR_BOOKING")

    # Priority 11: party spec
    has_vehicle = bool(payload.get("has_vehicle"))
    passenger_count = payload.get("passenger_count")
    vehicle_length_feet = payload.get("vehicle_length_feet")
    _validate_party_spec(passenger_count, has_vehicle, vehicle_length_feet)

    # Priority 13: EFFECTIVE fare schedule covering route+season at booking time
    fs = find_effective_schedule(sailing["route_id"], sailing["season"])
    if fs is None:
        raise_error(ERR_FARE_SCHEDULE_NOT_EFFECTIVE,
                    "No EFFECTIVE fare schedule covers the sailing")

    # Priority 14: capacity at quote time against pinned pools
    add_feet = int(vehicle_length_feet) if has_vehicle else 0
    _check_capacity(sailing, add_feet, int(passenger_count))

    # Quote pinned at creation (§3.5)
    quoted = booking_fare_quote(fs, customer["fare_class"], int(passenger_count),
                                has_vehicle, vehicle_length_feet, sailing["season"])

    ts = now_iso()
    booking = {
        "id": db.new_id(),
        "sailing_id": sailing_id,
        "customer_id": customer_id,
        "fare_schedule_id": fs["id"],
        "passenger_count": int(passenger_count),
        "has_vehicle": has_vehicle,
        "vehicle_length_feet": int(vehicle_length_feet) if has_vehicle else None,
        "status": "RESERVED",
        "quoted_fare_cents": quoted,
        "final_fare_cents": None,
        "rebooked_to_booking_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.bookings[booking["id"]] = booking
    # Reservations hold deck space from quote time (§2.7)
    recompute_sailing_counters(sailing)
    touch(sailing)
    return success_object(serialize_booking(booking), status=201)


@bp.get("/ferry/bookings/<booking_id>")
def get_booking(booking_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "Customer")
    booking = _get_booking(booking_id)
    return success_object(serialize_booking(booking))


@bp.get("/ferry/bookings")
def list_bookings():
    require_roles("SchedulerAdmin", "TerminalAgent", "Customer")
    fs_id = request.args.get("fare_schedule_id")
    rebooked_to = request.args.get("rebooked_to_booking_id")
    status = request.args.get("status")
    items = [b for b in db.bookings.values()
             if (fs_id is None or b.get("fare_schedule_id") == fs_id)
             and (rebooked_to is None or b.get("rebooked_to_booking_id") == rebooked_to)
             and (status is None or b["status"] == status)]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_booking(b) for b in page], meta)


@bp.post("/ferry/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    user_id, _role = require_roles("Customer")
    booking = _get_booking(booking_id)
    _check_owner(user_id, booking)

    if booking["status"] not in ("RESERVED", "MODIFIED"):
        raise_error(ERR_INVALID_STATE,
                    f"Cannot confirm a booking in status {booking['status']}")

    sailing = db.sailings[booking["sailing_id"]]
    # Priority 5: sailing posture for confirm
    if sailing["status"] not in ("OPEN_FOR_BOOKING", "BOOKING_CLOSED"):
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Sailing does not permit confirmation")

    customer = db.customers[booking["customer_id"]]

    # Fare settle: if pinned schedule still EFFECTIVE, settle == quoted; if
    # RETIRED, re-quote against currently EFFECTIVE schedule (§3.5).
    pinned = db.fare_schedules.get(booking["fare_schedule_id"])
    if pinned is not None and pinned["status"] == "EFFECTIVE":
        booking["final_fare_cents"] = booking["quoted_fare_cents"]
    else:
        fs = find_effective_schedule(sailing["route_id"], sailing["season"])
        if fs is None:
            raise_error(ERR_FARE_SCHEDULE_NOT_EFFECTIVE,
                        "No EFFECTIVE fare schedule covers the sailing")
        booking["fare_schedule_id"] = fs["id"]
        requote = booking_fare_quote(fs, customer["fare_class"],
                                     booking["passenger_count"],
                                     booking["has_vehicle"],
                                     booking.get("vehicle_length_feet"),
                                     sailing["season"])
        booking["quoted_fare_cents"] = requote
        booking["final_fare_cents"] = requote
    booking.pop("_requote", None)

    # Priority 14: capacity re-check at confirmation (exclude self — already held)
    add_feet = int(booking["vehicle_length_feet"]) if booking["has_vehicle"] else 0
    _check_capacity(sailing, add_feet, booking["passenger_count"],
                    exclude_booking_id=booking["id"])

    booking["status"] = "CONFIRMED"
    touch(booking)
    recompute_sailing_counters(sailing)
    touch(sailing)
    return success_object(serialize_booking(booking))


@bp.post("/ferry/bookings/<booking_id>/modify")
def modify_booking(booking_id):
    user_id, _role = require_roles("Customer")
    booking = _get_booking(booking_id)
    _check_owner(user_id, booking)

    if booking["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot modify a booking in status {booking['status']}")

    sailing = db.sailings[booking["sailing_id"]]
    if sailing["status"] != "OPEN_FOR_BOOKING":
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Sailing is not OPEN_FOR_BOOKING")

    payload = request.get_json(silent=True) or {}
    new_pax = int(payload.get("passenger_count", booking["passenger_count"]))
    new_has_vehicle = bool(payload.get("has_vehicle", booking["has_vehicle"]))
    new_length = payload.get("vehicle_length_feet", booking.get("vehicle_length_feet"))

    # Priority 11: party spec on the merged payload
    _validate_party_spec(new_pax, new_has_vehicle, new_length)

    # Growth capacity check (§3.5): if vehicle added or lengthened, the
    # requested feet must fit the remaining reservation pool.
    new_feet = int(new_length) if new_has_vehicle else 0
    old_feet = int(booking["vehicle_length_feet"]) if booking["has_vehicle"] else 0
    if new_feet > old_feet:
        _check_capacity(sailing, new_feet, new_pax,
                        exclude_booking_id=booking["id"])

    booking["passenger_count"] = new_pax
    booking["has_vehicle"] = new_has_vehicle
    booking["vehicle_length_feet"] = int(new_length) if new_has_vehicle else None

    # Re-quote against the pinned schedule (§3.5)
    customer = db.customers[booking["customer_id"]]
    pinned = db.fare_schedules.get(booking["fare_schedule_id"])
    if pinned is not None and pinned["status"] == "EFFECTIVE":
        quote_fs = pinned
    else:
        quote_fs = find_effective_schedule(sailing["route_id"], sailing["season"])
        if quote_fs is None:
            raise_error(ERR_FARE_SCHEDULE_NOT_EFFECTIVE,
                        "No EFFECTIVE fare schedule covers the sailing")
        booking["fare_schedule_id"] = quote_fs["id"]
    booking["quoted_fare_cents"] = booking_fare_quote(
        quote_fs, customer["fare_class"], new_pax, new_has_vehicle,
        booking.get("vehicle_length_feet"), sailing["season"])

    booking["status"] = "MODIFIED"
    touch(booking)
    recompute_sailing_counters(sailing)
    touch(sailing)
    return success_object(serialize_booking(booking))


@bp.post("/ferry/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, _role = require_roles("Customer")
    booking = _get_booking(booking_id)
    _check_owner(user_id, booking)

    if booking["status"] not in ("RESERVED", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE,
                    f"Cannot cancel a booking in status {booking['status']}")

    sailing = db.sailings[booking["sailing_id"]]

    if booking["status"] == "CONFIRMED":
        # Customer cancel of a settled booking only while OPEN_FOR_BOOKING
        if sailing["status"] != "OPEN_FOR_BOOKING":
            raise_error(ERR_SAILING_NOT_BOOKABLE,
                        "Sailing is not OPEN_FOR_BOOKING")
        customer = db.customers[booking["customer_id"]]
        customer["refund_credit_cents"] = int(customer.get("refund_credit_cents", 0)) + int(booking["final_fare_cents"])
        touch(customer)
    # RESERVED cancel: nothing settled, no refund.

    booking["status"] = "CANCELLED"
    touch(booking)
    recompute_sailing_counters(sailing)
    touch(sailing)
    return success_object(serialize_booking(booking))


@bp.post("/ferry/bookings/<booking_id>/rebook")
def rebook_booking(booking_id):
    user_id, _role = require_roles("Customer")
    booking = _get_booking(booking_id)
    _check_owner(user_id, booking)

    if booking["status"] != "CANCELLED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot rebook a booking in status {booking['status']}")

    # Operator-cancellation precondition: origin sailing must be CANCELLED
    origin_sailing = db.sailings[booking["sailing_id"]]
    if origin_sailing["status"] != "CANCELLED":
        raise_error(ERR_INVALID_STATE,
                    "Only operator-cancelled bookings may be rebooked")

    payload = request.get_json(silent=True) or {}
    target = db.sailings.get(payload.get("target_sailing_id"))
    if target is None:
        raise_error(ERR_NOT_FOUND, "Target sailing not found")

    # Priority 5: target sailing posture
    if target["status"] != "OPEN_FOR_BOOKING":
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Target sailing is not OPEN_FOR_BOOKING")

    # Priority 14: target reservation pool capacity for the same party
    add_feet = int(booking["vehicle_length_feet"]) if booking["has_vehicle"] else 0
    _check_capacity(target, add_feet, int(booking["passenger_count"]))

    customer = db.customers[booking["customer_id"]]

    # New booking directly CONFIRMED with carried-over fare (§3.8)
    carried = booking.get("final_fare_cents")
    ts = now_iso()
    new_booking = {
        "id": db.new_id(),
        "sailing_id": target["id"],
        "customer_id": booking["customer_id"],
        "fare_schedule_id": booking["fare_schedule_id"],
        "passenger_count": booking["passenger_count"],
        "has_vehicle": booking["has_vehicle"],
        "vehicle_length_feet": booking.get("vehicle_length_feet"),
        "status": "CONFIRMED",
        "quoted_fare_cents": carried,
        "final_fare_cents": carried,
        "rebooked_to_booking_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.bookings[new_booking["id"]] = new_booking

    # Consume the refund credit (§3.8)
    if carried:
        customer["refund_credit_cents"] = int(customer.get("refund_credit_cents", 0)) - int(carried)
        touch(customer)

    booking["status"] = "REBOOKED"
    booking["rebooked_to_booking_id"] = new_booking["id"]
    touch(booking)
    recompute_sailing_counters(target)
    touch(target)
    return success_object(serialize_booking(booking))


@bp.post("/ferry/bookings/<booking_id>/check-in")
def check_in_booking(booking_id):
    require_roles("TerminalAgent")
    booking = _get_booking(booking_id)

    if booking["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot check in a booking in status {booking['status']}")

    sailing = db.sailings[booking["sailing_id"]]
    # Check-in legal in BOOKING_CLOSED or BOARDING (§3.7)
    if sailing["status"] not in ("BOOKING_CLOSED", "BOARDING"):
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Sailing does not permit check-in")

    booking["status"] = "CHECKED_IN"
    touch(booking)
    return success_object(serialize_booking(booking))


@bp.post("/ferry/bookings/<booking_id>/board")
def board_booking(booking_id):
    require_roles("TerminalAgent")
    booking = _get_booking(booking_id)

    if booking["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot board a booking in status {booking['status']}")

    sailing = db.sailings[booking["sailing_id"]]
    if sailing["status"] != "BOARDING":
        raise_error(ERR_SAILING_NOT_BOOKABLE,
                    "Sailing is not BOARDING")

    booking["status"] = "BOARDED"
    touch(booking)
    return success_object(serialize_booking(booking))
