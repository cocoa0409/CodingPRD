"""Cohorts: formation and lifecycle (§3.3, §3.4)."""

from flask import Blueprint, request

from core import calc
from core.auth import authenticate
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import (LOSS_TYPES, WEEKDAYS, bad, body, iso_date, req_date, req_enum,
                        req_int, req_str)
from core.store import add_days, public, store
from services import cascade, derive, occupation
from services.state import must_exist, transition

bp = Blueprint("cohorts", __name__)

READ_ROLES = ["ProgramDirector", "IntakeCoordinator"]


@bp.route("/bereavement/cohorts", methods=["POST"])
def create_cohort():
    authenticate(["ProgramDirector"])
    data = body()
    name = req_str(data, "name")
    loss_type = req_enum(data, "loss_type", LOSS_TYPES)
    space_id = req_str(data, "meeting_space_id")
    seats_total = req_int(data, "seats_total", 1)
    min_viable = req_int(data, "min_viable_enrollment", 1)
    weekday = req_enum(data, "weekday", WEEKDAYS)
    start_minute = req_int(data, "start_minute_utc", 0, 1439)
    duration = req_int(data, "duration_minutes", 1)
    series_start = req_date(data, "series_start_date")
    sessions_total = req_int(data, "sessions_total", 1)
    direct_cost = req_int(data, "direct_cost_cents", 0)
    if start_minute + duration > 1440:
        bad("start_minute_utc + duration_minutes must not exceed 1440.")
    if calc.weekday_name(series_start) != weekday:
        bad("series_start_date must fall on the weekday named by weekday.")
    if min_viable > seats_total:
        bad("min_viable_enrollment must not exceed seats_total.")

    space = must_exist("MeetingSpace", space_id)

    series_end = add_days(series_start, 7 * (sessions_total - 1))
    occupation.check_cohort(space, weekday, series_start, series_end, start_minute, duration)

    if seats_total > space["capacity"]:
        raise ApiError("ERR_SPACE_CAPACITY_EXCEEDED", "seats_total exceeds the space capacity.")

    admin_fee, total = calc.program_cost(direct_cost)
    rec = store.create("Cohort", {
        "name": name,
        "loss_type": loss_type,
        "meeting_space_id": space_id,
        "seats_total": seats_total,
        "min_viable_enrollment": min_viable,
        "seats_held": 0,
        "seats_filled": 0,
        "seats_open": seats_total,
        "weekday": weekday,
        "start_minute_utc": start_minute,
        "duration_minutes": duration,
        "series_start_date": iso_date(series_start),
        "sessions_total": sessions_total,
        "series_end_date": iso_date(series_end),
        "status": "FORMING",
        "direct_cost_cents": direct_cost,
        "admin_fee_cents": admin_fee,
        "program_cost_total_cents": total,
    })
    return created(public(rec))


@bp.route("/bereavement/cohorts/<cid>", methods=["GET"])
def read_cohort(cid):
    authenticate(READ_ROLES)
    return ok(public(must_exist("Cohort", cid)))


@bp.route("/bereavement/cohorts", methods=["GET"])
def list_cohorts():
    authenticate(READ_ROLES)
    rows = store.all("Cohort")
    for key in ("meeting_space_id", "status", "loss_type"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/cohorts/<cid>/open-enrollment", methods=["POST"])
def open_enrollment(cid):
    authenticate(["ProgramDirector"])
    cohort = must_exist("Cohort", cid)
    body()
    transition(cohort, {"FORMING", "UNDERSUBSCRIBED"})
    space = store.get("MeetingSpace", cohort["meeting_space_id"])
    if space is None or space["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "The meeting space is not AVAILABLE.")
    cohort["status"] = "OPEN_ENROLLMENT"
    store.touch(cohort)
    return ok(public(cohort))


@bp.route("/bereavement/cohorts/<cid>/launch", methods=["POST"])
def launch(cid):
    authenticate(["ProgramDirector"])
    cohort = must_exist("Cohort", cid)
    body()
    transition(cohort, {"OPEN_ENROLLMENT"})
    if cohort["seats_filled"] >= cohort["min_viable_enrollment"]:
        cohort["status"] = "RUNNING"
        for enr in derive.cohort_enrollments(cid):
            if enr["status"] == "CONFIRMED":
                enr["status"] = "ATTENDING"
                store.touch(enr)
            elif enr["status"] == "HELD":
                enr["status"] = "EXPIRED"
                store.touch(enr)
        derive.recompute_seats(cohort)
    else:
        cohort["status"] = "UNDERSUBSCRIBED"
    store.touch(cohort)
    return ok(public(cohort))


@bp.route("/bereavement/cohorts/<cid>/suspend", methods=["POST"])
def suspend(cid):
    authenticate(["ProgramDirector"])
    cohort = must_exist("Cohort", cid)
    body()
    transition(cohort, {"RUNNING"})
    cascade.suspend_cohort(cohort)
    return ok(public(cohort))


@bp.route("/bereavement/cohorts/<cid>/resume", methods=["POST"])
def resume(cid):
    authenticate(["ProgramDirector"])
    cohort = must_exist("Cohort", cid)
    body()
    transition(cohort, {"SUSPENDED"})
    if cohort["seats_filled"] < cohort["min_viable_enrollment"]:
        raise ApiError("ERR_MIN_VIABLE_NOT_MET", "seats_filled is below min_viable_enrollment.")
    cohort["status"] = "RUNNING"
    store.touch(cohort)
    return ok(public(cohort))


@bp.route("/bereavement/cohorts/<cid>/complete", methods=["POST"])
def complete(cid):
    authenticate(["ProgramDirector"])
    cohort = must_exist("Cohort", cid)
    body()
    transition(cohort, {"RUNNING"})
    cohort["status"] = "COMPLETED"
    for enr in derive.cohort_enrollments(cid):
        if enr["status"] in ("CONFIRMED", "ATTENDING"):
            enr["status"] = "COMPLETED"
            enr["attendance_ratio"] = calc.attendance_ratio(enr["sessions_attended"],
                                                            cohort["sessions_total"])
            store.touch(enr)
            participant = store.get("Participant", enr["participant_id"])
            if participant is not None:
                participant["sessions_attended_total"] += enr["sessions_attended"]
                if participant["service_status"] == "ACTIVE":
                    participant["service_status"] = "MAINTENANCE"
                store.touch(participant)
    derive.recompute_seats(cohort)
    cascade.settle_allocations_for_cohort(cohort)
    store.touch(cohort)
    return ok(public(cohort))


@bp.route("/bereavement/cohorts/<cid>/cancel", methods=["POST"])
def cancel(cid):
    authenticate(["ProgramDirector"])
    cohort = must_exist("Cohort", cid)
    body()
    transition(cohort, {"FORMING", "OPEN_ENROLLMENT", "UNDERSUBSCRIBED", "SUSPENDED"})
    cohort["status"] = "CANCELLED"
    for enr in derive.cohort_enrollments(cid):
        if enr["status"] in ("HELD", "CONFIRMED", "ATTENDING"):
            enr["status"] = "WITHDRAWN"
            enr["withdraw_reason"] = "PROGRAM_CANCELLED"
            store.touch(enr)
    derive.recompute_seats(cohort)
    cascade.release_allocations_for_cohort(cohort)
    store.touch(cohort)
    return ok(public(cohort))
