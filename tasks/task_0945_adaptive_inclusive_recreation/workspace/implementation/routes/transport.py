"""Transport runs, positions and bookings."""

from datetime import timedelta

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import (
    Body,
    Refs,
    check_transition,
    check_version,
    endpoint,
    pagination,
    paginate,
    resolve_one,
)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, parse_instant, sort_rows, touch

bp = Blueprint("transport", __name__)

BOOKING_TERMINALS = ("RIDDEN", "NO_SHOW", "CANCELLED")


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------

@bp.route("/recreation/transport-runs", methods=["POST"])
@endpoint(roles=("TransportDispatcher",))
def create_run(context):
    session_id = context.body.get("session_id")
    session = None
    if isinstance(session_id, str):
        session = resolve_one("session", session_id)
    body = Body(context.body)
    body.req_string("session_id")
    pickup_start_at = body.req_instant("pickup_start_at")
    pickup_end_at = body.req_instant("pickup_end_at")
    fare_mode = body.req_enum("fare_mode", enums.FARE_MODES)
    flat_fare_cents = body.opt_int("flat_fare_cents", 0, minimum=0)
    route_miles_x10 = body.opt_int("route_miles_x10", 0, minimum=0)
    accessible_positions = body.req_int("accessible_positions", minimum=0)
    ambulatory_seats = body.req_int("ambulatory_seats", minimum=0)
    body.check_enums()
    if parse_instant(pickup_end_at) <= parse_instant(pickup_start_at):
        raise ApiError("ERR_VALIDATION", "pickup_end_at must be strictly later than pickup_start_at.")
    if session is None:
        session = resolve_one("session", session_id)

    row = insert(
        "transport_runs",
        {
            "session_id": session["id"],
            "pickup_start_at": pickup_start_at,
            "pickup_end_at": pickup_end_at,
            "fare_mode": fare_mode,
            "flat_fare_cents": flat_fare_cents,
            "route_miles_x10": route_miles_x10,
            "accessible_positions": accessible_positions,
            "accessible_committed": 0,
            "accessible_available": accessible_positions,
            "ambulatory_seats": ambulatory_seats,
            "ambulatory_committed": 0,
            "ambulatory_available": ambulatory_seats,
            "status": "PLANNED",
        },
    )
    return ok(serial.dump(row), 201)


@bp.route("/recreation/transport-runs", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_runs(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("transport_runs"))
    session_id = context.q("session_id")
    status = context.q("status")
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/transport-runs/<run_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_run(context, run_id):
    return ok(serial.dump(resolve_one("run", run_id)))


# ---------------------------------------------------------------------------
# bookings
# ---------------------------------------------------------------------------

@bp.route("/recreation/transport-bookings", methods=["POST"])
@endpoint(roles=("TransportDispatcher",))
def create_booking(context):
    raw = context.body
    refs = Refs()
    if isinstance(raw.get("enrollment_id"), str):
        refs.add("enrollment", raw["enrollment_id"], path=False)
    if isinstance(raw.get("transport_run_id"), str):
        refs.add("run", raw["transport_run_id"], path=False)
    refs.resolve()

    body = Body(raw)
    run_id = body.req_string("transport_run_id")
    enrollment_id = body.req_string("enrollment_id")
    position_type = body.req_enum("position_type", enums.POSITION_TYPES)
    expected_version = body.req_int("expected_run_version")
    body.check_enums()

    enrollment = resolve_one("enrollment", enrollment_id)
    run = resolve_one("run", run_id)
    check_version(expected_version, run)

    session = L.session_of_enrollment(enrollment)
    if run["session_id"] != session["id"]:                              # rung 30
        raise ApiError("ERR_PROGRAM_SESSION_MISMATCH")

    participant = L.participant_of_enrollment(enrollment)
    wanted = "ACCESSIBLE" if participant["mobility_profile"] == "WHEELCHAIR" else "AMBULATORY"
    if position_type != wanted:                                          # rung 52
        raise ApiError("ERR_POSITION_TYPE_MISMATCH")

    pickup_start = parse_instant(run["pickup_start_at"])                 # rung 53
    pickup_end = parse_instant(run["pickup_end_at"])
    latest = parse_instant(session["start_at"]) - timedelta(
        minutes=calc.TRANSPORT_ARRIVAL_BUFFER_MINUTES
    )
    if pickup_end > latest or pickup_start >= pickup_end:
        raise ApiError("ERR_TRANSPORT_WINDOW_MISMATCH")

    if position_type == "ACCESSIBLE":                                    # rung 54 / 55
        if run["accessible_available"] < 1:
            raise ApiError("ERR_ACCESSIBLE_POSITIONS_FULL")
    else:
        if run["ambulatory_available"] < 1:
            raise ApiError("ERR_AMBULATORY_SEATS_FULL")

    row = insert(
        "transport_bookings",
        {
            "transport_run_id": run["id"],
            "enrollment_id": enrollment["id"],
            "position_type": position_type,
            "fare_cents": calc.transport_fare_cents(run, position_type),
            "status": "RESERVED",
        },
    )
    engine.refresh_run_counters(run)
    engine.recompute_charge_of(enrollment)
    engine.refresh_run_status(run)
    return ok(serial.dump(row), 201)


@bp.route("/recreation/transport-bookings", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_bookings(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("transport_bookings"))
    run_id = context.q("transport_run_id")
    enrollment_id = context.q("enrollment_id")
    status = context.q("status")
    if run_id is not None:
        rows = [r for r in rows if r["transport_run_id"] == run_id]
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/transport-bookings/<booking_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_booking(context, booking_id):
    return ok(serial.dump(resolve_one("booking", booking_id)))


@bp.route("/recreation/transport-bookings/<booking_id>/confirm", methods=["POST"])
@endpoint(roles=("TransportDispatcher",))
def confirm_booking(context, booking_id):
    booking = resolve_one("booking", booking_id)
    check_transition(booking["status"], ("RESERVED",), BOOKING_TERMINALS)
    enrollment = L.enrollment_of_booking(booking)
    if enrollment["enrollment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "The enrolment is not confirmed.")
    booking["status"] = "CONFIRMED"
    touch(booking)
    return ok(serial.dump(booking))


@bp.route("/recreation/transport-bookings/<booking_id>/cancel", methods=["POST"])
@endpoint(roles=("TransportDispatcher", "IntakeCoordinator"))
def cancel_booking(context, booking_id):
    booking = resolve_one("booking", booking_id)
    check_transition(booking["status"], ("RESERVED", "CONFIRMED"), BOOKING_TERMINALS)
    engine.cancel_booking(booking)
    return ok(serial.dump(booking))
