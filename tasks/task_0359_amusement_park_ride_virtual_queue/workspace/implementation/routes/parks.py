"""Park lifecycle, admissions/exits, window advancement, and logical clock."""
from flask import Blueprint

import db
import domain
import errors
import lookups
import response
import serialize
import validate_input as vi
from middleware import get_principal, require_roles

bp = Blueprint("parks", __name__)


@bp.post("/parks")
def create_park():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    body = vi.get_body()

    name = vi.require_str(body, "name")
    gate_capacity = vi.require_int(body, "gate_capacity", min_val=1)
    operating_date = vi.require_str(body, "operating_date")
    peak = vi.opt_number(body, "peak_threshold_pct", default=0.85)
    if not (0 < peak <= 1):
        errors.err(errors.ERR_VALIDATION, "peak_threshold_pct must be in (0, 1]")

    park = db.stamp_new({
        "name": name,
        "gate_capacity": gate_capacity,
        "admitted_count": 0,
        "peak_threshold_pct": peak,
        "day_phase": "OPEN",
        "operating_date": operating_date,
        "current_utc": None,
    })
    db.parks[park["id"]] = park
    return response.object_response(serialize.view("park", park), 201)


@bp.get("/parks/<pid>")
def read_park(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    park = lookups.get_park(pid)
    return response.object_response(serialize.view("park", park), 200)


@bp.post("/parks/<pid>/admissions")
def admit(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    body = vi.get_body()
    ticket_id = vi.require_str(body, "ticket_id")
    ticket = lookups.get_ticket(ticket_id)

    # park-scope mismatch (PRD §2.10)
    if ticket["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Ticket belongs to a different park")

    # state precondition (priority 5)
    if ticket["admission_status"] != "ISSUED":
        errors.err(errors.ERR_INVALID_STATE, "Ticket is not ISSUED")
    if ticket["ticket_date"] != park["operating_date"]:
        errors.err(errors.ERR_INVALID_STATE, "Ticket date does not match operating date")

    # admission capacity (priority 14)
    if park["admitted_count"] >= park["gate_capacity"]:
        errors.err(errors.ERR_PARK_AT_CAPACITY, "Park is at gate capacity")

    ticket["admission_status"] = "ADMITTED"
    db.touch(ticket)
    park["admitted_count"] += 1
    domain.recompute_day_phase(park)
    db.touch(park)
    return response.object_response(serialize.view("guest_day_ticket", ticket), 201)


@bp.post("/parks/<pid>/exits")
def exit_gate(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    body = vi.get_body()
    ticket_id = vi.require_str(body, "ticket_id")
    ticket = lookups.get_ticket(ticket_id)

    if ticket["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Ticket belongs to a different park")

    if ticket["admission_status"] != "ADMITTED":
        errors.err(errors.ERR_INVALID_STATE, "Ticket is not ADMITTED")

    ticket["admission_status"] = "EXITED"
    db.touch(ticket)
    park["admitted_count"] -= 1
    domain.recompute_day_phase(park)
    db.touch(park)
    return response.object_response(serialize.view("guest_day_ticket", ticket), 201)


@bp.post("/parks/<pid>/advance-windows")
def advance_windows(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    now = domain.park_now(park)

    expired_window_count = 0
    forfeited_reservation_ids = []

    # Determine which windows belong to this park's rides.
    park_ride_ids = {r["id"] for r in db.rides.values() if r["park_id"] == park["id"]}

    for window in db.return_windows.values():
        if window["ride_id"] not in park_ride_ids:
            continue
        if window["window_status"] not in ("OPEN", "EXHAUSTED"):
            continue
        end = domain.parse_dt(window["window_end_utc"], "window_end_utc")
        if now is None or now < end:
            continue
        # window has elapsed -> EXPIRED, cascade forfeits
        window["window_status"] = "EXPIRED"
        db.touch(window)
        expired_window_count += 1
        ride = db.rides.get(window["ride_id"])
        for res in db.reservations.values():
            if res["return_window_id"] != window["id"]:
                continue
            if res["reservation_status"] not in ("HELD", "BOOKED"):
                continue
            res["reservation_status"] = "FORFEITED"
            db.touch(res)
            forfeited_reservation_ids.append(res["id"])
            if res["queue_type"] == "VIRTUAL_QUEUE":
                window["reserved_count"] -= 1
                db.touch(window)
                if ride is not None:
                    ride["booked_slot_count"] -= 1
        if ride is not None:
            domain.recompute_posted_wait(ride)
            db.touch(ride)

    return response.object_response({
        "expired_window_count": expired_window_count,
        "forfeited_reservation_ids": forfeited_reservation_ids,
    }, 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    body = vi.get_body()
    park_id = vi.require_str(body, "park_id")
    to_iso = vi.require_str(body, "to_iso8601")
    park = lookups.get_park(park_id)
    # validate the instant is parseable
    domain.parse_dt(to_iso, "to_iso8601")
    park["current_utc"] = to_iso
    db.touch(park)
    return response.object_response(serialize.view("park", park), 200)
