"""Press and machine reservation endpoints (PRD §2.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from store import STORE, now
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, not_found, stamp_new, bump)
from domain import (ser_press_res, ser_machine_res, iso_week_start,
                    machine_duration_hours, PRESSES, MACHINES,
                    COOLDOWN_BUFFER_HOURS, WEEKLY_CAPACITY_HOURS)

bp = Blueprint("reservations", __name__)


def _validate_window(start, end):
    """end_time strictly after start_time; start_time at or after now."""
    if end <= start or start < now():
        raise ApiError("ERR_INVALID_TIME_WINDOW", 422,
                       "Reservation requires end_time > start_time and start_time >= now")


# ---------------------------------------------------------------------------
# Press reservations: half-open [start, end); adjacency allowed.
# ---------------------------------------------------------------------------

@bp.route("/press-reservations", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def create_press_res(uid, role):
    data = validate_payload(get_body(), [
        ("build_job_id", "str", True),
        ("press_id", "enum", True, {"values": PRESSES}),
        ("start_time", "datetime", True),
        ("end_time", "datetime", True),
    ])
    job = STORE.jobs.get(data["build_job_id"])
    if job is None:
        not_found("BUILD_JOB")
    start, end = data["start_time"], data["end_time"]
    _validate_window(start, end)
    for other in STORE.press_res.values():
        if other["press_id"] != data["press_id"] or other["status"] != "RESERVED":
            continue
        if not (end <= other["start_time"] or start >= other["end_time"]):
            raise ApiError("ERR_PRESS_DOUBLE_BOOKED", 409,
                           "The press window overlaps an existing RESERVED window")
    res = stamp_new({
        "build_job_id": job["id"],
        "press_id": data["press_id"],
        "start_time": start,
        "end_time": end,
        "status": "RESERVED",
    })
    STORE.press_res[res["id"]] = res
    return created(ser_press_res(res))


@bp.route("/press-reservations", methods=["GET"])
@endpoint(roles=None)
def list_press_res(uid, role):
    items = sorted(STORE.press_res.values(), key=lambda r: (r["start_time"], r["_seq"]))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "press_id", request.args.get("press_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_press_res(r) for r in page], meta)


@bp.route("/press-reservations/<resId>", methods=["GET"])
@endpoint(roles=None)
def get_press_res(uid, role, resId):
    res = STORE.press_res.get(resId)
    if res is None:
        not_found("PRESS_RESERVATION")
    return ok(ser_press_res(res))


@bp.route("/press-reservations/<resId>/cancel", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def cancel_press_res(uid, role, resId):
    validate_payload(get_body(), [])
    res = STORE.press_res.get(resId)
    if res is None:
        not_found("PRESS_RESERVATION")
    if res["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RESERVED press window may be cancelled")
    for sample in STORE.samples.values():
        if (sample["press_reservation_id"] == res["id"]
                and sample["status"] in ("SCHEDULED", "SUBMITTED")):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "The window is referenced by an open tryout sample")
    res["status"] = "CANCELLED"
    bump(res)
    return ok(ser_press_res(res))


# ---------------------------------------------------------------------------
# Machine reservations: buffer-extended [start, end + 4h); 45h weekly capacity.
# ---------------------------------------------------------------------------

@bp.route("/machine-reservations", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def create_machine_res(uid, role):
    data = validate_payload(get_body(), [
        ("build_job_id", "str", True),
        ("machine_id", "enum", True, {"values": MACHINES}),
        ("start_time", "datetime", True),
        ("end_time", "datetime", True),
    ])
    job = STORE.jobs.get(data["build_job_id"])
    if job is None:
        not_found("BUILD_JOB")
    start, end = data["start_time"], data["end_time"]
    _validate_window(start, end)
    buffer = timedelta(hours=COOLDOWN_BUFFER_HOURS)
    for other in STORE.machine_res.values():
        if other["machine_id"] != data["machine_id"] or other["status"] != "RESERVED":
            continue
        if not (start >= other["end_time"] + buffer
                or other["start_time"] >= end + buffer):
            raise ApiError("ERR_MACHINE_WINDOW_CONFLICT", 409,
                           "The machine block overlaps another block's cool-down window")
    duration = machine_duration_hours(start, end)
    week_start = iso_week_start(start)
    week_end = week_start + timedelta(days=7)
    used = Decimal("0")
    for other in STORE.machine_res.values():
        if (other["machine_id"] == data["machine_id"] and other["status"] == "RESERVED"
                and week_start <= other["start_time"] < week_end):
            used += other["duration_hours"]
    if used + duration > WEEKLY_CAPACITY_HOURS:
        raise ApiError("ERR_MACHINE_CAPACITY_EXCEEDED", 409,
                       "The machine's weekly capacity of 45.0 hours would be exceeded")
    res = stamp_new({
        "build_job_id": job["id"],
        "machine_id": data["machine_id"],
        "start_time": start,
        "end_time": end,
        "duration_hours": duration,
        "status": "RESERVED",
    })
    STORE.machine_res[res["id"]] = res
    return created(ser_machine_res(res))


@bp.route("/machine-reservations", methods=["GET"])
@endpoint(roles=None)
def list_machine_res(uid, role):
    items = sorted(STORE.machine_res.values(), key=lambda r: (r["start_time"], r["_seq"]))
    items = filter_eq(items, "build_job_id", request.args.get("build_job_id"))
    items = filter_eq(items, "machine_id", request.args.get("machine_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_machine_res(r) for r in page], meta)


@bp.route("/machine-reservations/<resId>", methods=["GET"])
@endpoint(roles=None)
def get_machine_res(uid, role, resId):
    res = STORE.machine_res.get(resId)
    if res is None:
        not_found("MACHINE_RESERVATION")
    return ok(ser_machine_res(res))


@bp.route("/machine-reservations/<resId>/cancel", methods=["POST"])
@endpoint(roles=["ProjectManager"])
def cancel_machine_res(uid, role, resId):
    validate_payload(get_body(), [])
    res = STORE.machine_res.get(resId)
    if res is None:
        not_found("MACHINE_RESERVATION")
    if res["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a RESERVED machine block may be cancelled")
    res["status"] = "CANCELLED"
    bump(res)
    return ok(ser_machine_res(res))
