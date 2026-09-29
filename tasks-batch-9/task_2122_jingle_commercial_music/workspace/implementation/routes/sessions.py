"""Session calls, player bookings and settlement (PRD 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import ledger
import money
import response
import validators as v
import wages
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("sessions", __name__)

OCCUPYING_CALL_STATUSES = ("SCHEDULED", "SUSPENDED_BUDGET", "CONFIRMED", "COMPLETED")
OCCUPYING_BOOKING_STATUSES = ("BOOKED", "WAGE_ACCRUED", "PENALTY_ACCRUED")


def _set_hours(call, field, value):
    call["_" + field] = value
    call[field] = money.hours_json(value)


@bp.post("/session-calls")
@endpoint(["MusicHouseProducer"])
def create_session_call():
    body = v.get_body()
    project = None
    room = None
    if v.present(body, "project_id"):
        project = v.body_lookup(db.projects, body["project_id"], "ERR_PROJECT_NOT_FOUND")
    if v.present(body, "studio_room_id"):
        room = v.body_lookup(db.studio_rooms, body["studio_room_id"], "ERR_STUDIO_ROOM_NOT_FOUND")

    v.v_string(body, "project_id")
    v.v_string(body, "studio_room_id")
    start_raw, start_dt = v.v_datetime(body, "scheduled_start_utc")
    end_raw, end_dt = v.v_datetime(body, "scheduled_end_utc")

    if not end_dt > start_dt:
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    if project["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_PROJECT_NOT_IN_PRODUCTION")

    if room["status"] != "ACTIVE":
        raise ApiError("ERR_STUDIO_ROOM_UNAVAILABLE")

    # Half-open, zero-buffer room occupancy; exact adjacency is allowed.
    for other in db.session_calls.values():
        if other["studio_room_id"] != room["id"]:
            continue
        if other["status"] not in OCCUPYING_CALL_STATUSES:
            continue
        if start_dt < other["_end_dt"] and end_dt > other["_start_dt"]:
            raise ApiError("ERR_STUDIO_ROOM_DOUBLE_BOOKED")

    scheduled_hours = money.hours_between(start_dt, end_dt)
    record = db.create(db.session_calls, {
        "project_id": project["id"],
        "studio_room_id": room["id"],
        "scheduled_start_utc": start_raw,
        "scheduled_end_utc": end_raw,
        "actual_end_utc": None,
        "scheduled_hours": 0.0,
        "billed_hours": 0.0,
        "studio_cost_cents": 0,
        "wage_estimate_cents": 0,
        "committed_cents": 0,
        "wage_total_cents": 0,
        "settled_total_cents": 0,
        "wage_liability_cents": 0,
        "cancelled_at": None,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "_actual_end_dt": None,
    })
    _set_hours(record, "scheduled_hours", scheduled_hours)
    _set_hours(record, "billed_hours", scheduled_hours)
    return response.created(db.serialize(record))


@bp.get("/session-calls/<call_id>")
@endpoint(ALL_ROLES)
def get_session_call(call_id):
    call = v.path_lookup(db.session_calls, call_id, "ERR_SESSION_CALL_NOT_FOUND")
    return response.ok(db.serialize(call))


@bp.get("/session-calls")
@endpoint(ALL_ROLES)
def list_session_calls():
    rows = list(db.session_calls.values())
    project_id = request.args.get("project_id")
    room_id = request.args.get("studio_room_id")
    status = request.args.get("status")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if room_id:
        rows = [r for r in rows if r["studio_room_id"] == room_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/session-calls/<call_id>/bookings")
@endpoint(["MusicHouseProducer"])
def create_booking(call_id):
    call = v.path_lookup(db.session_calls, call_id, "ERR_SESSION_CALL_NOT_FOUND")
    body = v.get_body()
    musician = None
    if v.present(body, "musician_id"):
        musician = v.body_lookup(db.musicians, body["musician_id"], "ERR_MUSICIAN_NOT_FOUND")
    v.v_string(body, "musician_id")
    is_leader = v.v_bool(body, "is_leader", required=False, default=False)
    doubles_count = v.v_int(body, "doubles_count", required=False, default=0,
                            minimum=0, maximum=4)

    if call["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_CALL_INVALID_STATE")

    if musician["afm_member_status"] != "SIGNATORY_CLEARED":
        raise ApiError("ERR_MUSICIAN_NOT_SIGNATORY_CLEARED")

    existing = [b for b in db.bookings.values() if b["session_call_id"] == call["id"]]
    for booking in existing:
        if booking["musician_id"] == musician["id"] and booking["status"] != "RELEASED":
            raise ApiError("ERR_MUSICIAN_ALREADY_BOOKED")

    # Closed, buffered turnaround: 60 minutes of clear air on BOTH sides.
    buffer = timedelta(minutes=wages.AFM_TURNAROUND_BUFFER_MINUTES)
    for booking in db.bookings.values():
        if booking["musician_id"] != musician["id"]:
            continue
        if booking["session_call_id"] == call["id"]:
            continue
        if booking["status"] not in OCCUPYING_BOOKING_STATUSES:
            continue
        other = db.session_calls[booking["session_call_id"]]
        if other["status"] not in OCCUPYING_CALL_STATUSES:
            continue
        if call["_start_dt"] < other["_end_dt"] + buffer and \
                call["_end_dt"] + buffer > other["_start_dt"]:
            raise ApiError("ERR_MUSICIAN_TURNAROUND_CONFLICT")

    room = db.studio_rooms[call["studio_room_id"]]
    occupied = len([b for b in existing if b["status"] != "RELEASED"])
    if occupied + 1 > room["capacity_players"]:
        raise ApiError("ERR_SESSION_CAPACITY_EXCEEDED")

    record = db.create(db.bookings, {
        "session_call_id": call["id"],
        "musician_id": musician["id"],
        "is_leader": is_leader,
        "doubles_count": doubles_count,
        "line_wage_cents": 0,
        "pension_health_cents": 0,
        "status": "BOOKED",
    })
    return response.created(db.serialize(record))


@bp.get("/musician-bookings/<booking_id>")
@endpoint(ALL_ROLES)
def get_booking(booking_id):
    booking = v.path_lookup(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    return response.ok(db.serialize(booking))


@bp.get("/musician-bookings")
@endpoint(ALL_ROLES)
def list_bookings():
    rows = list(db.bookings.values())
    call_id = request.args.get("session_call_id")
    musician_id = request.args.get("musician_id")
    status = request.args.get("status")
    if call_id:
        rows = [r for r in rows if r["session_call_id"] == call_id]
    if musician_id:
        rows = [r for r in rows if r["musician_id"] == musician_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    items, meta = v.paginate(db.by_created(rows))
    return response.ok_list(items, meta)


@bp.post("/session-calls/<call_id>/confirm")
@endpoint(["MusicHouseProducer"])
def confirm_session_call(call_id):
    call = v.path_lookup(db.session_calls, call_id, "ERR_SESSION_CALL_NOT_FOUND")
    project = db.projects[call["project_id"]]

    if call["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_CALL_INVALID_STATE")
    if project["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_PROJECT_NOT_IN_PRODUCTION")
    if project["budget_posture"] != "HEALTHY":
        raise ApiError("ERR_PROJECT_BUDGET_CONSTRAINED")

    booked = wages.call_bookings(call["id"], ("BOOKED",))
    if not booked:
        raise ApiError("ERR_SESSION_CALL_INVALID_STATE",
                       "The call carries no booking line in BOOKED.")

    hours_basis = call["_scheduled_hours"]
    studio_cost = wages.studio_cost(call, hours_basis)
    wage_estimate = wages.wage_component(call, hours_basis, ("BOOKED",))
    committed = studio_cost + wage_estimate

    if project["available_cents"] < committed:
        raise ApiError("ERR_PROJECT_BUDGET_EXCEEDED")

    call["studio_cost_cents"] = studio_cost
    call["wage_estimate_cents"] = wage_estimate
    call["committed_cents"] = committed
    call["status"] = "CONFIRMED"
    db.touch(call)

    ledger.reserve(project, committed)
    ledger.recompute_posture(project)
    db.touch(project)

    return response.ok(db.serialize(call))


@bp.post("/session-calls/<call_id>/cancel")
@endpoint(["MusicHouseProducer"])
def cancel_session_call(call_id):
    call = v.path_lookup(db.session_calls, call_id, "ERR_SESSION_CALL_NOT_FOUND")
    project = db.projects[call["project_id"]]
    body = v.get_body()
    v.v_string(body, "reason")

    if call["status"] not in ("SCHEDULED", "SUSPENDED_BUDGET", "CONFIRMED"):
        raise ApiError("ERR_SESSION_CALL_INVALID_STATE")

    was_confirmed = call["status"] == "CONFIRMED"
    inside_window = False
    if was_confirmed:
        hours_before = money.exact_hours_between(clock.now(), call["_start_dt"])
        inside_window = hours_before < wages.AFM_CANCEL_WINDOW_HOURS

    booked = wages.call_bookings(call["id"], ("BOOKED",))

    if was_confirmed and inside_window:
        call["status"] = "CANCELLED_INSIDE_WINDOW"
        call["wage_liability_cents"] = call["wage_estimate_cents"]
        call["settled_total_cents"] = call["wage_estimate_cents"]
        for booking in booked:
            musician = db.musicians[booking["musician_id"]]
            wage, pension = wages.line_wage(musician, booking, call["_scheduled_hours"])
            booking["line_wage_cents"] = wage
            booking["pension_health_cents"] = pension
            booking["status"] = "PENALTY_ACCRUED"
            db.touch(booking)
    else:
        call["status"] = "CANCELLED_OUTSIDE_WINDOW"
        call["wage_liability_cents"] = 0
        call["settled_total_cents"] = 0
        for booking in booked:
            booking["line_wage_cents"] = 0
            booking["pension_health_cents"] = 0
            booking["status"] = "RELEASED"
            db.touch(booking)

    call["cancelled_at"] = clock.now_iso()
    db.touch(call)

    if was_confirmed:
        if inside_window:
            ledger.settle_partial(project, call["committed_cents"], call["wage_liability_cents"])
        else:
            ledger.release(project, call["committed_cents"])
        ledger.recompute_posture(project)
        db.touch(project)
    elif ledger.recompute_posture(project):
        db.touch(project)

    return response.ok(db.serialize(call))


@bp.post("/session-calls/<call_id>/complete")
@endpoint(["MusicHouseProducer"])
def complete_session_call(call_id):
    call = v.path_lookup(db.session_calls, call_id, "ERR_SESSION_CALL_NOT_FOUND")
    project = db.projects[call["project_id"]]
    body = v.get_body()
    actual_raw, actual_dt = v.v_datetime(body, "actual_end_utc")

    if not actual_dt > call["_start_dt"]:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    if call["status"] != "CONFIRMED":
        raise ApiError("ERR_SESSION_CALL_INVALID_STATE")

    # HOP 1 -- re-evaluate the call at the billed-hours basis.
    call["actual_end_utc"] = actual_raw
    call["_actual_end_dt"] = actual_dt
    billed_hours = money.hours_between(call["_start_dt"], actual_dt)
    _set_hours(call, "billed_hours", billed_hours)

    booked = wages.call_bookings(call["id"], ("BOOKED",))
    studio_cost = wages.studio_cost(call, billed_hours)
    wage_total = wages.wage_component(call, billed_hours, ("BOOKED",))
    call["studio_cost_cents"] = studio_cost
    call["wage_total_cents"] = wage_total
    call["settled_total_cents"] = studio_cost + wage_total
    call["status"] = "COMPLETED"
    db.touch(call)

    # HOP 2 -- the booking lines accrue their wages.
    for booking in booked:
        musician = db.musicians[booking["musician_id"]]
        wage, pension = wages.line_wage(musician, booking, billed_hours)
        booking["line_wage_cents"] = wage
        booking["pension_health_cents"] = pension
        booking["status"] = "WAGE_ACCRUED"
        db.touch(booking)

    # HOPS 3-5 -- ledger settlement, posture recompute, sweep.
    ledger.settle_partial(project, call["committed_cents"], call["settled_total_cents"])
    ledger.recompute_posture(project)
    db.touch(project)

    return response.ok(db.serialize(call))
