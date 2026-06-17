"""Reservation create and lifecycle transitions (PRD §3.3, §3.4)."""
from flask import Blueprint, request

import booking
import db
import domain
import errors
import lookups
import response
import serialize
import validate_input as vi
from middleware import get_principal, require_roles

bp = Blueprint("reservations", __name__)


@bp.post("/reservations")
def create_reservation():
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    body = vi.get_body()

    ride_id = vi.require_str(body, "ride_id")
    guest_id = vi.require_str(body, "guest_id")
    return_window_id = vi.require_str(body, "return_window_id")
    queue_type = vi.require_enum(body, "queue_type", {"VIRTUAL_QUEUE", "SINGLE_RIDER"})
    expected_version = vi.require_int(body, "expected_return_window_id_version")

    # existence, left-to-right (priority 3)
    ride = lookups.get_ride(ride_id)
    guest = lookups.get_guest(guest_id)
    window = lookups.get_window(return_window_id)

    # ownership (priority 4)
    if guest["id"] != user_id:
        errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Acting guest does not own this reservation")

    # park scope: ride and window must align (window belongs to ride; guest/ride
    # share a park)
    if window["ride_id"] != ride["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Window does not belong to the ride")
    if guest["park_id"] != ride["park_id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Guest belongs to a different park")

    park = db.parks.get(ride["park_id"])

    # OCC (priority 6): expected_return_window_id_version vs ReturnWindow.version
    if expected_version != window["version"]:
        errors.err(errors.ERR_STALE_VERSION, "Return window version is stale")

    # height (priority 7)
    booking.check_height(guest, ride)
    # accessibility (priority 8)
    booking.check_accessibility(guest, ride)

    if queue_type == "VIRTUAL_QUEUE":
        # temporal window (priority 9): window must not have elapsed
        booking.check_window_not_elapsed(window, park)
        # peak gate (priority 10)
        booking.check_peak_gate(park, guest)
        # VQ ceiling (priority 11)
        booking.check_vq_ceiling(guest)
        # window exhaustion (priority 13)
        booking.check_window_capacity(window)
        res = booking.create_vq_reservation(ride, guest, window, park)
    else:
        # SINGLE_RIDER consumes no slot; height/accessibility still applied above.
        res = booking.create_single_rider_reservation(ride, guest, window)

    return response.object_response(serialize.view("reservation", res), 201)


@bp.get("/reservations")
def list_reservations():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    ride_id = request.args.get("ride_id")
    guest_id = request.args.get("guest_id")
    return_window_id = request.args.get("return_window_id")
    party_id = request.args.get("party_id")
    rfw = request.args.get("redistributed_from_window_id")
    records = list(db.reservations.values())
    if ride_id is not None:
        records = [r for r in records if r["ride_id"] == ride_id]
    if guest_id is not None:
        records = [r for r in records if r["guest_id"] == guest_id]
    if return_window_id is not None:
        records = [r for r in records if r["return_window_id"] == return_window_id]
    if party_id is not None:
        records = [r for r in records if r["party_id"] == party_id]
    if rfw is not None:
        records = [r for r in records if r["redistributed_from_window_id"] == rfw]
    return lookups.paginate_and_respond("reservation", records, response)


@bp.get("/reservations/<rid>")
def read_reservation(rid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    res = lookups.get_reservation(rid)
    return response.object_response(serialize.view("reservation", res), 200)


@bp.post("/reservations/<rid>/confirm")
def confirm_reservation(rid):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    res = lookups.get_reservation(rid)

    # ownership (priority 4)
    if res["guest_id"] != user_id:
        errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Acting guest does not own this reservation")

    ride = db.rides.get(res["ride_id"])
    window = db.return_windows.get(res["return_window_id"])

    # state (priority 5): HELD, parent ride OPEN, and (VQ) owning window OPEN
    if res["reservation_status"] != "HELD":
        errors.err(errors.ERR_INVALID_STATE, "Reservation is not HELD")
    if ride is None or ride["operational_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "Parent ride is not OPEN")
    if res["queue_type"] == "VIRTUAL_QUEUE":
        if window is None or window["window_status"] != "OPEN":
            errors.err(errors.ERR_INVALID_STATE, "Owning window is not OPEN")

    res["reservation_status"] = "BOOKED"
    db.touch(res)
    domain.recompute_posted_wait(ride)
    db.touch(ride)
    return response.object_response(serialize.view("reservation", res), 200)


@bp.post("/reservations/<rid>/redeem")
def redeem_reservation(rid):
    _, role = get_principal()
    require_roles(role, {"RideOperator"})
    res = lookups.get_reservation(rid)

    ride = db.rides.get(res["ride_id"])
    window = db.return_windows.get(res["return_window_id"])
    park = db.parks.get(ride["park_id"]) if ride else None

    # state (priority 5): BOOKED, parent ride OPEN
    if res["reservation_status"] != "BOOKED":
        errors.err(errors.ERR_INVALID_STATE, "Reservation is not BOOKED")
    if ride is None or ride["operational_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "Parent ride is not OPEN")

    # height re-check (priority 7)
    guest = db.guests.get(res["guest_id"])
    if guest is not None and guest["height_cm"] < ride["min_height_cm"]:
        errors.err(errors.ERR_HEIGHT_REQUIREMENT_NOT_MET, "Guest height below ride minimum")

    # temporal window (priority 9): for VQ, current_utc within [start, end)
    if res["queue_type"] == "VIRTUAL_QUEUE":
        now = domain.park_now(park)
        start = domain.parse_dt(window["window_start_utc"], "window_start_utc")
        end = domain.parse_dt(window["window_end_utc"], "window_end_utc")
        if now is None or not (start <= now < end):
            errors.err(errors.ERR_WINDOW_NOT_REDEEMABLE, "Outside the redeemable window")

    res["reservation_status"] = "REDEEMED"
    db.touch(res)

    if res["queue_type"] == "VIRTUAL_QUEUE":
        if window is not None:
            window["reserved_count"] -= 1
            db.touch(window)
            domain.maybe_unexhaust_window(window, park)
        ride["booked_slot_count"] -= 1

    domain.recompute_posted_wait(ride)
    db.touch(ride)
    return response.object_response(serialize.view("reservation", res), 200)


@bp.post("/reservations/<rid>/cancel")
def cancel_reservation(rid):
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    res = lookups.get_reservation(rid)

    # ownership (priority 4)
    if res["guest_id"] != user_id:
        errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Acting guest does not own this reservation")

    # state (priority 5): only while HELD
    if res["reservation_status"] != "HELD":
        errors.err(errors.ERR_INVALID_STATE, "Reservation is not HELD")

    ride = db.rides.get(res["ride_id"])
    window = db.return_windows.get(res["return_window_id"])
    park = db.parks.get(ride["park_id"]) if ride else None

    res["reservation_status"] = "FORFEITED"
    db.touch(res)

    if res["queue_type"] == "VIRTUAL_QUEUE":
        if window is not None:
            window["reserved_count"] -= 1
            db.touch(window)
            domain.maybe_unexhaust_window(window, park)
        if ride is not None:
            ride["booked_slot_count"] -= 1

    if ride is not None:
        domain.recompute_posted_wait(ride)
        db.touch(ride)
    return response.object_response(serialize.view("reservation", res), 200)
