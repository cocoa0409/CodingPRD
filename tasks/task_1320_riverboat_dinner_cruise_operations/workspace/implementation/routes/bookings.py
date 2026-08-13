"""Bookings, booking passengers, payment, cancellation, boarding check-in."""
from flask import Blueprint, request

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_json, paginate, get_or_404, touch, check_str

bp = Blueprint("bookings", __name__)

CUSTOMER = ["Customer"]
ALL_READ = ["OperationsManager", "Captain", "CharterSalesAgent", "Customer", "GalleyManager", "DockAttendant"]

BOOKING_STATUSES = ["RESERVED", "CONFIRMED", "BOARDED", "NO_SHOW", "CANCELLED", "CONVERTED_TO_CHARTER"]
PAYMENT_STATUSES = ["PENDING", "PAID", "REFUND_PENDING", "REFUNDED", "CREDITED"]


@bp.post("/cruises/<cid>/bookings")
def create_booking(cid):
    uid, _ = require_auth(CUSTOMER)
    body = get_json(required_fields=["customer_id", "party_size", "expected_cruise_version"],
                    optional_fields=["bar_package_count"])
    # Request shape
    party_size = body["party_size"]
    if isinstance(party_size, bool) or not isinstance(party_size, int) or party_size < 1:
        raise err_invalid_request("party_size must be an integer >= 1")
    bar_count = body.get("bar_package_count", 0)
    if bar_count is None:
        bar_count = 0
    if isinstance(bar_count, bool) or not isinstance(bar_count, int) or bar_count < 0:
        raise err_invalid_request("bar_package_count must be an integer >= 0")
    if bar_count > party_size:
        raise err_invalid_request("bar_package_count must be <= party_size")
    expected_version = body["expected_cruise_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err_invalid_request("expected_cruise_version must be an integer")
    customer_id = body["customer_id"]
    if not isinstance(customer_id, str):
        raise err_invalid_request("customer_id must be a string")

    # Path existence (rung 3)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    customer = db.customers.get(customer_id)
    if customer is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["customer"], "Customer not found")

    # Rung 5: cruise must be SCHEDULED
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")

    # Rung 6: capacity — resulting reserved_covers within the certified cap
    vessel = db.vessels[cruise["vessel_id"]]
    if cruise["reserved_covers"] + party_size > vessel["coast_guard_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "Resulting reserved_covers would exceed coast_guard_capacity")

    # Rung 14: OCC on the cruise
    if expected_version != cruise["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_cruise_version is stale")

    now_z = clock.to_z(clock.now())
    total, bar_total = svc.compute_booking_totals(cruise, party_size, bar_count)
    booking = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "cruise_id": cruise["id"], "customer_id": customer["id"],
        "party_size": party_size,
        "booking_total_cents": total,
        "bar_package_count": bar_count,
        "bar_package_total_cents": bar_total,
        "payment_status": "PENDING",
        "booking_status": "RESERVED",
    }
    db.insert(db.bookings, booking)
    svc.recompute_reserved_covers(cruise)  # bumps cruise version by 1
    return ok(_sz("booking", booking), status=201)


@bp.get("/cruises/<cid>/bookings")
def list_cruise_bookings(cid):
    require_auth(ALL_READ)
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    bs = request.args.get("booking_status")
    ps = request.args.get("payment_status")
    cust = request.args.get("customer_id")
    if bs is not None and bs not in BOOKING_STATUSES:
        raise err_invalid_request("Invalid value for booking_status")
    if ps is not None and ps not in PAYMENT_STATUSES:
        raise err_invalid_request("Invalid value for payment_status")
    items = [b for b in db.bookings.values() if b["cruise_id"] == cruise["id"]]
    if bs is not None:
        items = [b for b in items if b["booking_status"] == bs]
    if ps is not None:
        items = [b for b in items if b["payment_status"] == ps]
    if cust is not None:
        items = [b for b in items if b["customer_id"] == cust]
    items.sort(key=lambda b: b["created_at"])
    page, meta = paginate(items)
    return ok(_szl("booking", page), pagination=meta)


@bp.get("/bookings/<bid>")
def get_booking(bid):
    require_auth(ALL_READ)
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    return ok(_sz("booking", booking))


@bp.get("/bookings/<bid>/passengers")
def list_passengers(bid):
    require_auth(["OperationsManager", "Captain", "Customer", "DockAttendant"])
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    items = sorted((p for p in db.passengers.values() if p["booking_id"] == booking["id"]),
                   key=lambda p: p["created_at"])
    page, meta = paginate(items)
    return ok(_szl("passenger", page), pagination=meta)


@bp.post("/bookings/<bid>/passengers")
def add_passenger(bid):
    require_auth(CUSTOMER)
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    body = get_json(required_fields=["full_name", "date_of_birth"])
    full_name = check_str(body, "full_name")
    dob = clock.parse_date(body["date_of_birth"])
    if dob is None:
        raise err_invalid_request("date_of_birth must be an ISO date")
    cruise = db.cruises[booking["cruise_id"]]
    now_z = clock.to_z(clock.now())
    passenger = {
        "id": db.new_id(), "created_at": now_z,
        "booking_id": booking["id"],
        "full_name": full_name,
        "date_of_birth": body["date_of_birth"],
        "is_minor": svc.is_minor_dob(dob, clock.parse_dt(cruise["depart_at"])),
        "boarded_at": None,
    }
    db.insert(db.passengers, passenger)
    return ok(_sz("passenger", passenger), status=201)


@bp.post("/bookings/<bid>/pay")
def pay_booking(bid):
    require_auth(CUSTOMER)
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    if not (booking["payment_status"] == "PENDING"
            and booking["booking_status"] in ("RESERVED", "CONFIRMED")):
        raise err_invalid_state("Booking is not payable in its current state")
    cruise = db.cruises[booking["cruise_id"]]
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")
    if booking["bar_package_count"] > 0 and not cruise["bar_service_enabled"]:
        raise ApiError("ERR_BAR_SERVICE_UNAVAILABLE", 409,
                       "bar_service_enabled is false on this cruise")
    total, bar_total = svc.compute_booking_totals(
        cruise, booking["party_size"], booking["bar_package_count"])
    booking["booking_total_cents"] = total
    booking["bar_package_total_cents"] = bar_total
    booking["payment_status"] = "PAID"
    if booking["booking_status"] == "RESERVED":
        booking["booking_status"] = "CONFIRMED"
    touch(booking)
    svc.recompute_reserved_covers(cruise)
    return ok(_sz("booking", booking))


@bp.post("/bookings/<bid>/cancel")
def cancel_booking(bid):
    require_auth(CUSTOMER)
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    if booking["booking_status"] not in ("RESERVED", "CONFIRMED"):
        raise err_invalid_state("Booking is not cancellable in its current state")
    cruise = db.cruises[booking["cruise_id"]]
    if cruise["status"] != "SCHEDULED":
        raise ApiError("ERR_CRUISE_NOT_BOOKABLE", 409, "Cruise is not SCHEDULED")
    booking["booking_status"] = "CANCELLED"
    if booking["payment_status"] == "PAID":
        booking["payment_status"] = "REFUNDED"
    touch(booking)
    svc.recompute_reserved_covers(cruise)
    return ok(_sz("booking", booking))


@bp.post("/bookings/<bid>/passengers/<pid>/check-in")
def check_in_passenger(bid, pid):
    require_auth(["DockAttendant"])
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    passenger = db.passengers.get(pid)
    if passenger is None or passenger["booking_id"] != booking["id"]:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["passenger"], "Booking passenger not found")
    cruise = db.cruises[booking["cruise_id"]]
    if cruise["status"] != "BOARDING":
        raise err_invalid_state("Cruise is not BOARDING")
    if passenger["boarded_at"] is not None:
        raise err_invalid_state("Passenger already boarded")
    vessel = db.vessels[cruise["vessel_id"]]
    if cruise["boarded_count"] + 1 > vessel["coast_guard_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                       "boarded_count would exceed coast_guard_capacity")
    passenger["boarded_at"] = clock.to_z(clock.now())
    svc.recompute_boarded_count(cruise)
    # Auto-advance the booking to BOARDED when all of its passengers have boarded
    if booking["booking_status"] == "CONFIRMED":
        pax = [p for p in db.passengers.values() if p["booking_id"] == booking["id"]]
        if pax and all(p["boarded_at"] is not None for p in pax):
            booking["booking_status"] = "BOARDED"
            touch(booking)
            svc.recompute_boarded_count(cruise)
            manifest = svc.manifest_for_cruise(cruise["id"])
            if manifest is not None:
                svc.refresh_manifest_count(manifest)
    return ok(_sz("passenger", passenger))


@bp.get("/bookings/<bid>/parking-passes")
def booking_parking_passes(bid):
    require_auth(["OperationsManager", "DockAttendant", "Customer"])
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    items = sorted((p for p in db.parking_passes.values() if p["booking_id"] == booking["id"]),
                   key=lambda p: p["created_at"])
    page, meta = paginate(items)
    return ok(_szl("parking_pass", page), pagination=meta)


@bp.get("/bookings/<bid>/charter-cruises")
def booking_charter_cruises(bid):
    require_auth(["OperationsManager", "CharterSalesAgent", "Customer"])
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    items = sorted((c for c in db.cruises.values() if c.get("charter_booking_id") == booking["id"]),
                   key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return ok(_szl("cruise", page), pagination=meta)


@bp.get("/bookings/<bid>/credits")
def booking_credits(bid):
    require_auth(["OperationsManager", "CharterSalesAgent", "Customer"])
    booking = get_or_404(db.bookings, bid, "booking", "Booking not found")
    items = sorted((c for c in db.credits.values() if c["booking_id"] == booking["id"]),
                   key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return ok(_szl("credit", page), pagination=meta)
