"""Gear rental routes (PRD §3.6). OCC on Booking.version, gear capacity."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, require_str, require_int, get_pagination, paginate,
    get_or_404, stamp_common, touch,
)
from response import success_object, success_array
from serialize import public, public_list
from services import calc
from services import booking_logic as bl

bp = Blueprint("gear_rentals", __name__)


def _owns_booking(principal, booking):
    if principal.role == "Client" and booking["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only act on their own bookings")


@bp.route("/studio/bookings/<bid>/gear-rentals", methods=["POST"])
def add_gear_rental(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    booking = get_or_404(db.bookings, bid, "booking")
    if principal.role == "Client":
        _owns_booking(principal, booking)

    body = get_json_body()
    gear_item_id = require_str(body, "gear_item_id")
    units = require_int(body, "units")
    expected_version = require_int(body, "expected_booking_version")

    # Semantic well-formedness screen (PRD §2.12): units >= 1. The PRD frames
    # ERR_VALIDATION as part of the early structural screen, before the ordered
    # domain checks, so it precedes the OCC token check.
    if units < 1:
        raise err("ERR_VALIDATION", "units must be >= 1")

    # Existence of FK body (after path).
    gear = get_or_404(db.gear_items, gear_item_id, "gear item")

    # OCC (priority 6 in the validations table): runs after existence/ownership
    # and before the capacity business check (priority 11). No state transition
    # gates a gear-rental add — the booking just must exist.
    if expected_version != booking["version"]:
        raise err("ERR_STALE_VERSION", "expected_booking_version does not match booking version")

    # Gear capacity (PRD §3.6): sum of units across RESERVED rentals of the
    # same gear item whose booking windows overlap the new booking's window
    # must not exceed total_units.
    my_start, my_end = bl.booking_window(booking)
    reserved_overlap_units = 0
    for r in db.gear_rentals.values():
        if r["gear_item_id"] != gear_item_id:
            continue
        if r["status"] != "RESERVED":
            continue
        other_booking = db.bookings.get(r["booking_id"])
        if other_booking is None:
            continue
        o_start, o_end = bl.booking_window(other_booking)
        if bl.intervals_overlap(my_start, my_end, o_start, o_end):
            reserved_overlap_units += r["units"]
    if reserved_overlap_units + units > gear["total_units"]:
        raise err("ERR_GEAR_UNAVAILABLE", "gear rental exceeds available units")

    # Pricing (PRD §3.6).
    rental_days = calc.gear_rental_days(my_start, my_end)
    charge = calc.gear_charge_cents(units, rental_days, gear["daily_rate_cents"])

    rental = {
        "booking_id": bid,
        "gear_item_id": gear_item_id,
        "units": units,
        "rental_days": rental_days,
        "charge_cents": charge,
        "status": "RESERVED",
    }
    stamp_common(rental)
    db.gear_rentals[rental["id"]] = rental

    # Reconcile booking total and bump booking version (OCC mutation).
    bl.reconcile_total(booking)
    touch(booking)
    return success_object(public(rental), status=201)


@bp.route("/studio/bookings/<bid>/gear-rentals", methods=["GET"])
def list_booking_gear_rentals(bid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    get_or_404(db.bookings, bid, "booking")
    rentals = [r for r in db.gear_rentals.values() if r["booking_id"] == bid]
    limit, offset = get_pagination()
    page, total = paginate(rentals, limit, offset)
    return success_array(public_list(page), limit, offset, total)


@bp.route("/studio/gear-rentals/<rid>", methods=["GET"])
def get_gear_rental(rid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    rental = get_or_404(db.gear_rentals, rid, "gear rental")
    return success_object(public(rental))


@bp.route("/studio/gear-rentals", methods=["GET"])
def list_gear_rentals():
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client", "Engineer"})
    gear_item_id = request.args.get("gear_item_id")
    booking_id = request.args.get("booking_id")
    rentals = list(db.gear_rentals.values())
    if gear_item_id is not None:
        rentals = [r for r in rentals if r["gear_item_id"] == gear_item_id]
    if booking_id is not None:
        rentals = [r for r in rentals if r["booking_id"] == booking_id]
    limit, offset = get_pagination()
    page, total = paginate(rentals, limit, offset)
    return success_array(public_list(page), limit, offset, total)


@bp.route("/studio/bookings/<bid>/gear-rentals/<rental_id>", methods=["DELETE"])
def release_gear_rental(bid, rental_id):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    booking = get_or_404(db.bookings, bid, "booking")
    rental = get_or_404(db.gear_rentals, rental_id, "gear rental")
    # Nested ownership: rental must belong to the booking in the path.
    if rental["booking_id"] != bid:
        raise err("ERR_NOT_FOUND", "gear rental does not belong to this booking")

    # State: parent booking must not be COMPLETED; rental must be RESERVED.
    if booking["schedule_status"] == "COMPLETED":
        raise err("ERR_INVALID_STATE", "cannot release rental on a completed booking")
    if rental["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "rental is not RESERVED")

    rental["status"] = "RELEASED"
    touch(rental)
    # PRD §3.6 / scaffold DELETE side effects: status RESERVED->RELEASED, free
    # reserved units, increment GearRental.version. The freed units fall out of
    # future capacity/total computations because reconcile_total and the
    # capacity check both ignore RELEASED rentals. The booking version is NOT
    # bumped here (only add-gear-rental carries the OCC booking-version bump).
    return success_object(public(rental))
