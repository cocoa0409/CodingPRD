"""Worker / Shift / ShiftAssignment endpoints (PRD §3.8)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import db, new_record, touch, parse_ts
from errors import (
    ApiError, not_found, invalid_request,
    ERR_WORKER_NOT_ACTIVE, ERR_WORKER_CAP_REACHED, ERR_SHIFT_FULL,
    ERR_SHIFT_OVERLAP, ERR_WEEKLY_HOURS_EXCEEDED, ERR_ASSIGNMENT_INVALID_STATE,
    ERR_FORBIDDEN_OWNERSHIP,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services import calc
from services.helpers import recompute_shift_assigned_count

bp = Blueprint("workforce", __name__)

EMPLOYMENT_TYPES = ["VOLUNTEER", "TRANSITIONAL", "STAFF"]
ROLE_TYPES = ["SORTER", "PRICER", "CASHIER", "DRIVER", "FLOOR", "INTAKE"]


def worker_view(w):
    return dict(w)


def shift_view(s):
    return dict(s)


def assignment_view(a):
    return dict(a)


def _get_worker(worker_id):
    w = db.workers.get(worker_id)
    if w is None:
        raise not_found("worker")
    return w


def _get_shift(shift_id):
    s = db.shifts.get(shift_id)
    if s is None:
        raise not_found("shift")
    return s


def _get_assignment(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise not_found("shift assignment")
    return a


def _iso_week_monday(dt):
    """Monday 00:00 UTC bounding the week containing dt."""
    d = dt.date()
    monday = d - timedelta(days=d.weekday())
    from datetime import datetime, timezone
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


@bp.route("/api/workers", methods=["POST"])
def create_worker():
    require_roles(["VolunteerCoordinator"])
    payload = get_body(
        required=[("full_name", "string"), ("employment_type", "string")],
        optional=[("email", "string"), ("program_cap_hours", "number")],
        enums={"employment_type": EMPLOYMENT_TYPES},
    )
    cap = payload.get("program_cap_hours", calc.DEFAULT_PROGRAM_CAP_HOURS)
    if float(cap) <= 0:
        raise invalid_request("program_cap_hours must be > 0")
    rec = new_record()
    rec.update({
        "full_name": payload["full_name"],
        "employment_type": payload["employment_type"],
        "email": payload.get("email"),
        "status": "ACTIVE",
        "credited_hours": 0,
        "program_cap_hours": cap,
        "cap_extension_hours": 0,
    })
    db.workers[rec["id"]] = rec
    return success_object(worker_view(rec), status=201)


@bp.route("/api/workers/<worker_id>", methods=["GET"])
def get_worker(worker_id):
    require_roles(ALL_ROLES)
    return success_object(worker_view(_get_worker(worker_id)))


@bp.route("/api/workers/<worker_id>", methods=["PATCH"])
def patch_worker(worker_id):
    user_id, role = require_roles(["VolunteerCoordinator", "StoreManager"])
    payload = get_body(
        optional=[("status", "string"), ("cap_extension_hours", "number"),
                  ("email", "string")],
        enums={"status": ["ACTIVE", "INACTIVE"]},
    )
    worker = _get_worker(worker_id)
    changed = False
    if "status" in payload:
        # VolunteerCoordinator toggles ACTIVE<->INACTIVE
        worker["status"] = payload["status"]
        changed = True
    if "email" in payload:
        worker["email"] = payload["email"]
        changed = True
    if "cap_extension_hours" in payload:
        ext = payload["cap_extension_hours"]
        if float(ext) < 0:
            raise invalid_request("cap_extension_hours must be >= 0")
        worker["cap_extension_hours"] = ext
        changed = True
        # CAP_REACHED -> ACTIVE when the extension lifts the effective cap
        effective_cap = float(worker["program_cap_hours"]) + float(ext)
        if worker["status"] == "CAP_REACHED" and effective_cap > float(worker["credited_hours"]):
            worker["status"] = "ACTIVE"
    if changed:
        touch(worker)
    return success_object(worker_view(worker))


@bp.route("/api/shifts", methods=["POST"])
def create_shift():
    require_roles(["VolunteerCoordinator"])
    payload = get_body(
        required=[("role_type", "string"), ("starts_at", "string"),
                  ("ends_at", "string"), ("required_headcount", "integer")],
        enums={"role_type": ROLE_TYPES},
    )
    try:
        s_start = parse_ts(payload["starts_at"])
        s_end = parse_ts(payload["ends_at"])
    except (ValueError, TypeError):
        raise invalid_request("starts_at/ends_at must be ISO8601 timestamps")
    if not s_end > s_start:
        raise invalid_request("ends_at must be strictly after starts_at")
    if payload["required_headcount"] < 1:
        raise invalid_request("required_headcount must be >= 1")
    rec = new_record()
    rec.update({
        "role_type": payload["role_type"],
        "starts_at": payload["starts_at"],
        "ends_at": payload["ends_at"],
        "required_headcount": payload["required_headcount"],
        "assigned_count": 0,
    })
    db.shifts[rec["id"]] = rec
    return success_object(shift_view(rec), status=201)


@bp.route("/api/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    require_roles(ALL_ROLES)
    return success_object(shift_view(_get_shift(shift_id)))


@bp.route("/api/shifts/<shift_id>/assignments", methods=["POST"])
def create_assignment(shift_id):
    require_roles(["VolunteerCoordinator"])
    payload = get_body(required=[("worker_id", "string")])
    shift = _get_shift(shift_id)
    worker = db.workers.get(payload["worker_id"])
    if worker is None:
        raise not_found("worker")
    # seat capacity (priority 9)
    recompute_shift_assigned_count(shift)
    if shift["assigned_count"] >= shift["required_headcount"]:
        raise ApiError(ERR_SHIFT_FULL, 422, "Shift is at capacity")
    # worker status gates (priority 11 referential; ordered here with the other
    # business gates — INACTIVE/CAP_REACHED are worker-status rejections)
    if worker["status"] == "INACTIVE":
        raise ApiError(ERR_WORKER_NOT_ACTIVE, 422, "Worker is INACTIVE")
    if worker["status"] == "CAP_REACHED":
        raise ApiError(ERR_WORKER_CAP_REACHED, 422,
                       "Worker has reached the TRANSITIONAL program cap")
    # double-booking (temporal): overlapping [start,end), touching allowed, no buffer
    new_start = parse_ts(shift["starts_at"])
    new_end = parse_ts(shift["ends_at"])
    for a in db.assignments.values():
        if a["worker_id"] != worker["id"] or a["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        other = db.shifts.get(a["shift_id"])
        if other is None:
            continue
        o_start = parse_ts(other["starts_at"])
        o_end = parse_ts(other["ends_at"])
        if new_start < o_end and o_start < new_end:
            raise ApiError(ERR_SHIFT_OVERLAP, 422,
                           "Worker already holds an overlapping assignment")
    # TRANSITIONAL weekly cap (priority 9): same ISO week (Monday 00:00Z boundary)
    if worker["employment_type"] == "TRANSITIONAL":
        new_duration = calc.shift_duration_hours(shift)
        week_start = _iso_week_monday(new_start)
        week_end = week_start + timedelta(days=7)
        load = Decimal("0")
        for a in db.assignments.values():
            if a["worker_id"] != worker["id"]:
                continue
            if a["status"] not in ("ASSIGNED", "CONFIRMED", "COMPLETED"):
                continue
            other = db.shifts.get(a["shift_id"])
            if other is None:
                continue
            o_start = parse_ts(other["starts_at"])
            if week_start <= o_start < week_end:
                load += Decimal(str(calc.shift_duration_hours(other)))
        if load + Decimal(str(new_duration)) > calc.WEEKLY_CAP_HOURS:
            raise ApiError(ERR_WEEKLY_HOURS_EXCEEDED, 422,
                           "TRANSITIONAL weekly hours would exceed 20.0")
    rec = new_record()
    rec.update({
        "shift_id": shift["id"],
        "worker_id": worker["id"],
        "status": "ASSIGNED",
        "credited_hours_applied": None,
    })
    db.assignments[rec["id"]] = rec
    recompute_shift_assigned_count(shift)
    touch(shift)
    return success_object(assignment_view(rec), status=201)


@bp.route("/api/shift-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_roles(ALL_ROLES)
    return success_object(assignment_view(_get_assignment(assignment_id)))


@bp.route("/api/shift-assignments", methods=["GET"])
def list_assignments():
    require_roles(ALL_ROLES)
    filters = query_filters(["shift_id", "worker_id", "status"])
    records = apply_filters(list(db.assignments.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([assignment_view(a) for a in page], limit, offset, total)


@bp.route("/api/shift-assignments/<assignment_id>/confirm", methods=["POST"])
def confirm_assignment(assignment_id):
    user_id, role = require_roles(["Volunteer", "VolunteerCoordinator"])
    get_body()
    a = _get_assignment(assignment_id)
    # ownership: Volunteer may confirm only their own
    if role == "Volunteer" and user_id != a["worker_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Volunteer may confirm only their own assignment")
    if a["status"] != "ASSIGNED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "confirm requires an ASSIGNED assignment")
    a["status"] = "CONFIRMED"
    touch(a)
    return success_object(assignment_view(a))


@bp.route("/api/shift-assignments/<assignment_id>/complete", methods=["POST"])
def complete_assignment(assignment_id):
    require_roles(["VolunteerCoordinator"])
    get_body()
    a = _get_assignment(assignment_id)
    if a["status"] != "CONFIRMED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "complete requires a CONFIRMED assignment")
    shift = db.shifts.get(a["shift_id"])
    worker = db.workers.get(a["worker_id"])
    hours = calc.shift_duration_hours(shift)
    a["credited_hours_applied"] = hours
    a["status"] = "COMPLETED"
    touch(a)
    if worker is not None:
        worker["credited_hours"] = round(
            float(worker["credited_hours"]) + float(hours), 2)
        # TRANSITIONAL program cap: landing exactly on the cap flips the worker
        effective_cap = float(worker["program_cap_hours"]) + float(worker["cap_extension_hours"])
        if worker["employment_type"] == "TRANSITIONAL" \
                and float(worker["credited_hours"]) >= effective_cap:
            worker["status"] = "CAP_REACHED"
        touch(worker)
    if shift is not None:
        recompute_shift_assigned_count(shift)
        touch(shift)
    return success_object(assignment_view(a))


@bp.route("/api/shift-assignments/<assignment_id>/no-show", methods=["POST"])
def no_show_assignment(assignment_id):
    require_roles(["VolunteerCoordinator"])
    get_body()
    a = _get_assignment(assignment_id)
    if a["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "no-show requires an ASSIGNED or CONFIRMED assignment")
    a["status"] = "NO_SHOW"
    touch(a)
    shift = db.shifts.get(a["shift_id"])
    if shift is not None:
        recompute_shift_assigned_count(shift)
        touch(shift)
    return success_object(assignment_view(a))


@bp.route("/api/shift-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    user_id, role = require_roles(["Volunteer", "VolunteerCoordinator"])
    get_body()
    a = _get_assignment(assignment_id)
    if role == "Volunteer" and user_id != a["worker_id"]:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Volunteer may cancel only their own assignment")
    if a["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, 409,
                       "cancel requires an ASSIGNED or CONFIRMED assignment")
    a["status"] = "CANCELLED"
    touch(a)
    shift = db.shifts.get(a["shift_id"])
    if shift is not None:
        recompute_shift_assigned_count(shift)
        touch(shift)
    return success_object(assignment_view(a))
