"""Routes: workers, labor shifts, shift assignments."""

from datetime import timedelta, date
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import (get_body, get_body_optional, pagination_params, parse_date, parse_dt,
                  req_int, req_str, req_enum, dec, q2)
from services.core import (
    stamp_new, touch, logical_now,
    get_worker, get_shift, get_assignment,
    ser_worker, ser_shift, ser_assignment,
    intervals_overlap_half_open, iso_week_bounds, worker_hours_in_week,
    recompute_worker_weekly_hours, recompute_shift_overtime,
    ROLE_TYPES, WEEKLY_HOURS_HARD_CAP,
)
from services.calculations import compute_projected_labor_cost

bp = Blueprint("labor", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


# ---------------------------------------------------------------- workers
@bp.post("/workers")
def create_worker():
    require_roles("LaborPlanner")
    body = get_body({"full_name", "certifications", "hourly_rate_cents"},
                    {"full_name", "certifications", "hourly_rate_cents"})
    name = req_str(body["full_name"], "full_name")
    certs = body["certifications"]
    if not isinstance(certs, list) or not all(isinstance(c, str) for c in certs):
        raise_error("ERR_INVALID_REQUEST", "certifications must be an array of strings")
    for c in certs:
        if c not in ROLE_TYPES:
            raise_error("ERR_INVALID_REQUEST", f"invalid certification {c}")
    rate = req_int(body["hourly_rate_cents"], "hourly_rate_cents")
    if rate < 0:
        raise_error("ERR_INVALID_REQUEST", "hourly_rate_cents must be non-negative")
    worker = stamp_new({
        "full_name": name, "certifications": list(certs),
        "hourly_rate_cents": rate,
        "scheduled_hours_current_week": Decimal("0"),
    })
    store.workers[worker["id"]] = worker
    return success(ser_worker(worker), status=201)


@bp.get("/workers")
def list_workers():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.workers.values())
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    return list_response(items, ser_worker, limit, offset)


@bp.get("/workers/<wid>")
def get_worker_route(wid):
    require_roles(*ALL_ROLES)
    worker = get_worker(wid)
    recompute_worker_weekly_hours(worker)
    return success(ser_worker(worker))


@bp.get("/workers/<wid>/assignments")
def list_worker_assignments(wid):
    require_roles(*ALL_ROLES)
    worker = get_worker(wid)
    limit, offset = pagination_params()
    items = [a for a in store.shift_assignments.values() if a["worker_id"] == worker["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return list_response(items, ser_assignment, limit, offset)


# ---------------------------------------------------------------- shifts
@bp.post("/labor-shifts")
def create_shift():
    require_roles("LaborPlanner")
    fields = {"shift_date", "role_type", "start_at", "end_at", "headcount_required",
              "planned_hourly_rate_cents"}
    body = get_body(fields, fields)
    shift_date = parse_date(body["shift_date"], "shift_date")
    role_type = req_enum(body["role_type"], "role_type", ROLE_TYPES)
    start_at = parse_dt(body["start_at"], "start_at")
    end_at = parse_dt(body["end_at"], "end_at")
    headcount = req_int(body["headcount_required"], "headcount_required")
    rate = req_int(body["planned_hourly_rate_cents"], "planned_hourly_rate_cents")
    if start_at.date() != shift_date:
        raise_error("ERR_INVALID_REQUEST", "start_at must fall on shift_date")
    if end_at <= start_at:
        raise_error("ERR_INVALID_REQUEST", "end_at must be after start_at")
    if headcount <= 0:
        raise_error("ERR_INVALID_REQUEST", "headcount_required must be positive")
    if rate < 0:
        raise_error("ERR_INVALID_REQUEST", "planned_hourly_rate_cents must be non-negative")
    shift = stamp_new({
        "shift_date": shift_date, "role_type": role_type,
        "start_at": start_at, "end_at": end_at,
        "headcount_required": headcount,
        "headcount_assigned": 0,
        "planned_hourly_rate_cents": rate,
        "projected_labor_cost_cents": 0,
        "overtime_hours": Decimal("0"),
        "shift_status": "DRAFT",
    })
    store.labor_shifts[shift["id"]] = shift
    return success(ser_shift(shift), status=201)


@bp.get("/labor-shifts")
def list_shifts():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.labor_shifts.values())
    sd = _q("shift_date")
    rt = _q("role_type")
    st = _q("shift_status")
    if sd is not None:
        items = [s for s in items if (s["shift_date"].isoformat() if isinstance(s["shift_date"], date) else s["shift_date"]) == sd]
    if rt is not None:
        items = [s for s in items if s["role_type"] == rt]
    if st is not None:
        items = [s for s in items if s["shift_status"] == st]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return list_response(items, ser_shift, limit, offset)


@bp.get("/labor-shifts/<sid>")
def get_shift_route(sid):
    require_roles(*ALL_ROLES)
    shift = get_shift(sid)
    return success(ser_shift(shift))


@bp.get("/labor-shifts/<sid>/assignments")
def list_shift_assignments(sid):
    require_roles(*ALL_ROLES)
    shift = get_shift(sid)
    limit, offset = pagination_params()
    items = [a for a in store.shift_assignments.values() if a["shift_id"] == shift["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    return list_response(items, ser_assignment, limit, offset)


@bp.post("/labor-shifts/<sid>/publish")
def publish_shift(sid):
    require_roles("LaborPlanner")
    get_body_optional(set())
    shift = get_shift(sid)
    if shift["shift_status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shift not DRAFT")
    shift["shift_status"] = "PUBLISHED"
    compute_projected_labor_cost(shift)
    touch(shift)
    return success(ser_shift(shift))


@bp.post("/labor-shifts/<sid>/assignments")
def create_assignment(sid):
    require_roles("LaborPlanner")
    body = get_body({"worker_id", "expected_labor_shift_version"},
                    {"worker_id", "expected_labor_shift_version"})
    shift = get_shift(sid)
    worker_id = body["worker_id"]
    if not isinstance(worker_id, str):
        raise_error("ERR_INVALID_REQUEST", "worker_id must be a string")
    worker = store.workers.get(worker_id)
    if worker is None:
        raise_error("ERR_NOT_FOUND", "Worker not found")
    expected = body["expected_labor_shift_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error("ERR_INVALID_REQUEST", "expected_labor_shift_version must be an integer")
    # cross-entity state (priority 6)
    if shift["shift_status"] != "PUBLISHED":
        raise_error("ERR_SHIFT_NOT_PUBLISHED", "Shift not PUBLISHED")
    # certification (priority 10)
    if shift["role_type"] not in worker["certifications"]:
        raise_error("ERR_CERTIFICATION_MISSING", "Worker lacks certification")
    # overlap (priority 9): worker's other assignments' shifts half-open overlap
    for a in store.shift_assignments.values():
        if a["worker_id"] != worker["id"] or a["assignment_status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        other = store.labor_shifts.get(a["shift_id"])
        if other is None or other["id"] == shift["id"]:
            continue
        if intervals_overlap_half_open(shift["start_at"], shift["end_at"], other["start_at"], other["end_at"]):
            raise_error("ERR_SHIFT_OVERLAP", "Worker has overlapping assignment")
    # headcount (priority 10)
    if shift.get("headcount_assigned", 0) + 1 > shift["headcount_required"]:
        raise_error("ERR_HEADCOUNT_EXCEEDED", "headcount exceeded")
    # weekly hours hard cap (priority 10): ISO week containing TARGET shift's shift_date
    sd = shift["shift_date"]
    if isinstance(sd, str):
        sd = date.fromisoformat(sd)
    ws, _we = iso_week_bounds(sd)
    current_hours = worker_hours_in_week(worker["id"], ws)
    new_hours = Decimal(str((shift["end_at"] - shift["start_at"]).total_seconds())) / Decimal("3600")
    if current_hours + new_hours > WEEKLY_HOURS_HARD_CAP:
        raise_error("ERR_WEEKLY_HOURS_EXCEEDED", "Weekly hours cap exceeded")
    # OCC (priority 11)
    if expected != shift["version"]:
        raise_error("ERR_STALE_VERSION", "Stale shift version")
    assignment = stamp_new({
        "shift_id": shift["id"], "worker_id": worker["id"],
        "assignment_status": "ASSIGNED",
    })
    store.shift_assignments[assignment["id"]] = assignment
    shift["headcount_assigned"] = shift.get("headcount_assigned", 0) + 1
    recompute_shift_overtime(shift)
    compute_projected_labor_cost(shift)
    touch(shift)
    recompute_worker_weekly_hours(worker)
    touch(worker)
    return success(ser_assignment(assignment), status=201)


@bp.post("/labor-shifts/<sid>/assignments/<aid>/confirm")
def confirm_assignment(sid, aid):
    user_id, _ = require_roles("Worker")
    get_body_optional(set())
    shift = get_shift(sid)
    assignment = get_assignment(aid)
    if assignment["shift_id"] != shift["id"]:
        raise_error("ERR_NOT_FOUND", "Assignment does not belong to shift")
    # ownership / segregation (priority 3)
    if assignment["worker_id"] != user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES", "Worker may only confirm own assignment")
    if shift["shift_status"] != "PUBLISHED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shift not PUBLISHED")
    if assignment["assignment_status"] != "ASSIGNED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Assignment not ASSIGNED")
    assignment["assignment_status"] = "CONFIRMED"
    touch(assignment)
    return success(ser_assignment(assignment))


@bp.post("/labor-shifts/<sid>/assignments/<aid>/release")
def release_assignment(sid, aid):
    require_roles("LaborPlanner")
    get_body_optional(set())
    shift = get_shift(sid)
    assignment = get_assignment(aid)
    if assignment["shift_id"] != shift["id"]:
        raise_error("ERR_NOT_FOUND", "Assignment does not belong to shift")
    if assignment["assignment_status"] not in ("ASSIGNED", "CONFIRMED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Assignment not ASSIGNED/CONFIRMED")
    assignment["assignment_status"] = "RELEASED"
    touch(assignment)
    shift["headcount_assigned"] = max(0, shift.get("headcount_assigned", 0) - 1)
    recompute_shift_overtime(shift)
    touch(shift)
    worker = store.workers.get(assignment["worker_id"])
    if worker is not None:
        recompute_worker_weekly_hours(worker)
        touch(worker)
    return success(ser_assignment(assignment))


@bp.post("/labor-shifts/<sid>/complete")
def complete_shift(sid):
    require_roles("LaborPlanner")
    get_body_optional(set())
    shift = get_shift(sid)
    if shift["shift_status"] != "PUBLISHED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shift not PUBLISHED")
    if logical_now() < shift["end_at"]:
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shift has not ended")
    for a in store.shift_assignments.values():
        if a["shift_id"] == shift["id"] and a["assignment_status"] == "ASSIGNED":
            raise_error("ERR_UNCONFIRMED_ASSIGNMENTS", "Assignments remain ASSIGNED")
    shift["shift_status"] = "COMPLETED"
    touch(shift)
    return success(ser_shift(shift))


@bp.post("/labor-shifts/<sid>/cancel")
def cancel_shift(sid):
    require_roles("LaborPlanner")
    get_body_optional(set())
    shift = get_shift(sid)
    if shift["shift_status"] not in ("DRAFT", "PUBLISHED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Shift not DRAFT/PUBLISHED")
    affected_workers = set()
    for a in store.shift_assignments.values():
        if a["shift_id"] == shift["id"] and a["assignment_status"] in ("ASSIGNED", "CONFIRMED"):
            a["assignment_status"] = "RELEASED"
            touch(a)
            affected_workers.add(a["worker_id"])
    shift["headcount_assigned"] = 0
    shift["shift_status"] = "CANCELED"
    touch(shift)
    for wid in affected_workers:
        w = store.workers.get(wid)
        if w is not None:
            recompute_worker_weekly_hours(w)
            touch(w)
    return success(ser_shift(shift))
