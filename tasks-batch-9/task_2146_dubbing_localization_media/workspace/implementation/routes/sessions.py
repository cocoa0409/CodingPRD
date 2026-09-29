"""Recording sessions: booking, waitlist, confirm, start, complete, cancel, no-show."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, auth
from domain import (add_studio_minutes, add_talent_held, check_order_open,
                    cascade_order_to_recording_on_schedule, get_assignment, get_order,
                    get_session, get_studio, move_held_to_recorded, order_adaptation,
                    recompute_assignment_minutes, run_waitlist_promotion,
                    studio_buffered_conflict, studio_day_minutes, talent_closed_conflict,
                    talent_day_minutes, rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import db, new_row, serialize, touch
from validate import body, v_bool, v_datetime, v_enum, v_string

bp = Blueprint("sessions", __name__)


def _cost_for(session, studio, assignment, talent):
    return calc.session_cost_cents(
        session["duration_minutes"],
        studio["hourly_rate_cents"],
        assignment["agreed_rate_cents_per_hour"],
        talent["union_status"],
        session["is_retake"],
    )


@bp.post("/recording-sessions")
@auth("ProductionCoordinator")
def create_session():
    data = body()
    order = get_order(data.get("order_id"))                     # rung 7
    studio = get_studio(data.get("studio_id"))
    assignment = get_assignment(data.get("casting_assignment_id"))
    start_utc = v_datetime(data, "start_utc")                   # rung 8
    end_utc = v_datetime(data, "end_utc")
    is_retake = v_bool(data, "is_retake", required=False, default=False)
    on_conflict = v_enum(data, "on_conflict", ("REJECT", "WAITLIST"),
                         required=False, default="REJECT")

    check_order_open(order)                                     # rung 10
    if assignment["order_id"] != order["id"]:                   # rung 20
        raise ApiError("ERR_CROSS_ORDER_REFERENCE")
    if studio["status"] != "ACTIVE":                            # rung 37
        raise ApiError("ERR_STUDIO_UNAVAILABLE")

    # rung 38: window validity
    if start_utc >= end_utc:
        raise ApiError("ERR_SESSION_WINDOW_INVALID")
    if (start_utc.second, start_utc.microsecond) != (0, 0):
        raise ApiError("ERR_SESSION_WINDOW_INVALID")
    if (end_utc.second, end_utc.microsecond) != (0, 0):
        raise ApiError("ERR_SESSION_WINDOW_INVALID")
    if start_utc < db.clock:
        raise ApiError("ERR_SESSION_WINDOW_INVALID")

    duration_minutes = int((end_utc - start_utc).total_seconds() // 60)

    slot_conflict = studio_buffered_conflict(studio, start_utc, end_utc)
    day_booked = studio_day_minutes(studio, start_utc)
    capacity_short = (day_booked + duration_minutes) > studio["daily_capacity_minutes"]

    if on_conflict == "REJECT":
        if slot_conflict:                                       # rung 39
            raise ApiError("ERR_STUDIO_SLOT_CONFLICT")
        if capacity_short:                                      # rung 40
            raise ApiError("ERR_STUDIO_DAILY_CAPACITY")

    talent = db.voice_talents[assignment["talent_id"]]
    if talent_closed_conflict(talent["id"], start_utc, end_utc):     # rung 41
        raise ApiError("ERR_TALENT_DOUBLE_BOOKED")
    talent_day = talent_day_minutes(talent["id"], start_utc)         # rung 42
    if (talent_day + duration_minutes) > talent["max_daily_recorded_minutes"]:
        raise ApiError("ERR_TALENT_DAILY_CAP_EXCEEDED")

    if slot_conflict:
        status, reason = "WAITLISTED", "STUDIO_SLOT_CONFLICT"
    elif capacity_short:
        status, reason = "WAITLISTED", "STUDIO_DAILY_CAPACITY"
    else:
        status, reason = "SCHEDULED", None

    row = new_row({
        "order_id": order["id"],
        "studio_id": studio["id"],
        "casting_assignment_id": assignment["id"],
        "status": status,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "duration_minutes": duration_minutes,
        "is_retake": is_retake,
        "session_cost_cents": 0,
        "waitlisted_reason": reason,
    })
    row["session_cost_cents"] = _cost_for(row, studio, assignment, talent)
    db.sessions[row["id"]] = row

    if status == "SCHEDULED":
        add_studio_minutes(studio, duration_minutes)
        add_talent_held(talent, duration_minutes)
        cascade_order_to_recording_on_schedule(order)
    return created(serialize(row))


@bp.get("/recording-sessions/<session_id>")
@auth(*ALL_ROLES)
def read_session(session_id):
    return ok(serialize(get_session(session_id)))


@bp.get("/recording-sessions")
@auth(*ALL_ROLES)
def list_sessions():
    rows = list(db.sessions.values())
    for key in ("order_id", "studio_id", "casting_assignment_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/recording-sessions/<session_id>/confirm")
@auth("ProductionCoordinator")
def confirm_session(session_id):
    session = get_session(session_id)
    order = db.orders[session["order_id"]]
    check_order_open(order)                                   # rung 10
    if session["status"] != "SCHEDULED":                      # rung 11
        raise ApiError("ERR_INVALID_STATE")
    adaptation = order_adaptation(order["id"])                # rung 26
    if adaptation is None or adaptation["status"] != "APPROVED":
        raise ApiError("ERR_ADAPTATION_NOT_APPROVED")
    assignment = db.assignments[session["casting_assignment_id"]]
    if assignment["casting_status"] not in ("CONFIRMED", "RECORDED"):
        raise ApiError("ERR_INVALID_STATE")
    studio = db.studios[session["studio_id"]]                 # rung 37
    if studio["status"] != "ACTIVE":
        raise ApiError("ERR_STUDIO_UNAVAILABLE")
    session["status"] = "CONFIRMED"
    touch(session)
    return ok(serialize(session))


@bp.post("/recording-sessions/<session_id>/start")
@auth("ProductionCoordinator")
def start_session(session_id):
    session = get_session(session_id)
    order = db.orders[session["order_id"]]
    check_order_open(order)
    if session["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    if db.clock < session["start_utc"]:
        raise ApiError("ERR_INVALID_STATE")
    session["status"] = "IN_PROGRESS"
    touch(session)
    return ok(serialize(session))


@bp.post("/recording-sessions/<session_id>/complete")
@auth("ProductionCoordinator")
def complete_session(session_id):
    session = get_session(session_id)
    order = db.orders[session["order_id"]]
    check_order_open(order)                                   # rung 10
    if session["status"] != "IN_PROGRESS":                    # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if order["status"] != "RECORDING":
        raise ApiError("ERR_INVALID_STATE")

    studio = db.studios[session["studio_id"]]
    assignment = db.assignments[session["casting_assignment_id"]]
    talent = db.voice_talents[assignment["talent_id"]]
    cost = _cost_for(session, studio, assignment, talent)

    if order["committed_cents"] + cost > order["budget_cap_cents"]:    # rung 43
        raise ApiError("ERR_BUDGET_EXCEEDED")

    session["session_cost_cents"] = cost
    session["status"] = "COMPLETED"
    touch(session)

    move_held_to_recorded(talent, session["duration_minutes"])
    order["committed_cents"] = order["committed_cents"] + cost
    order["gross_accrued_cents"] = order["gross_accrued_cents"] + cost
    touch(order)

    if session["is_retake"]:
        for item in rows_where(db.retake_items,
                               casting_assignment_id=assignment["id"], status="OPEN"):
            item["status"] = "RECORDED"
            touch(item)

    recompute_assignment_minutes(assignment)
    if assignment["casting_status"] == "CONFIRMED":
        assignment["casting_status"] = "RECORDED"
    touch(assignment)
    return ok(serialize(session))


@bp.post("/recording-sessions/<session_id>/cancel")
@auth("ProductionCoordinator")
def cancel_session(session_id):
    session = get_session(session_id)
    data = body()
    v_string(data, "reason", required=False, default=None, non_empty=False)
    order = db.orders[session["order_id"]]
    check_order_open(order)                                   # rung 10
    if session["status"] not in ("WAITLISTED", "SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")                   # rung 11

    was_holding = session["status"] in ("SCHEDULED", "CONFIRMED")
    session["status"] = "CANCELLED"
    touch(session)

    if was_holding:
        studio = db.studios[session["studio_id"]]
        assignment = db.assignments[session["casting_assignment_id"]]
        talent = db.voice_talents[assignment["talent_id"]]
        add_studio_minutes(studio, -session["duration_minutes"])
        add_talent_held(talent, -session["duration_minutes"])
        run_waitlist_promotion(studio)
    return ok(serialize(session))


@bp.post("/recording-sessions/<session_id>/no-show")
@auth("ProductionCoordinator")
def no_show_session(session_id):
    session = get_session(session_id)
    order = db.orders[session["order_id"]]
    check_order_open(order)
    if session["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    if db.clock < session["start_utc"]:
        raise ApiError("ERR_INVALID_STATE")

    session["status"] = "NO_SHOW"
    touch(session)

    studio = db.studios[session["studio_id"]]
    assignment = db.assignments[session["casting_assignment_id"]]
    talent = db.voice_talents[assignment["talent_id"]]
    add_studio_minutes(studio, -session["duration_minutes"])
    add_talent_held(talent, -session["duration_minutes"])
    run_waitlist_promotion(studio)
    return ok(serialize(session))
