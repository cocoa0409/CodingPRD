"""Workers, productivity standards and labor budget discipline."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import const
import fields
from authz import ALL_ROLES, GROWER_MANAGER, HARVEST_SUPERVISOR, body, guard
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, terminal, to_status_enum, transition
from money import D, q2
from store import base_record, db, now, ordered, touch

bp = Blueprint("labor", __name__)


# ------------------------------------------------------------------ Worker


@bp.post("/workers")
@guard([GROWER_MANAGER])
def create_worker():
    payload = body()
    full_name = fields.string(payload, "full_name", min_len=1)
    skill = fields.enum_slot(payload, "skill")
    hourly_rate = fields.number(payload, "hourly_rate_usd", lo=0, exclusive_lo=True)
    productivity = fields.number(
        payload, "productivity_index", required=False, lo="0.5", hi="2.0"
    )
    status = fields.enum_slot(payload, "status", required=False)
    fields.enum_value(skill, "skill", const.WORKER_SKILLS)
    fields.enum_value(status, "status", const.WORKER_STATUSES)

    record = base_record()
    record.update({
        "full_name": full_name,
        "skill": skill,
        "hourly_rate_usd": q2(hourly_rate),
        "productivity_index": q2(productivity) if productivity is not None else q2(1),
        "status": status or "ACTIVE",
        "committed_hours": q2(0),
    })
    db["workers"][record["id"]] = record
    return created(public(record))


@bp.get("/workers")
@guard(ALL_ROLES)
def list_workers():
    rows = ordered("workers")
    rows = filter_equals(rows, "skill", request.args.get("skill"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/workers/<worker_id>")
@guard(ALL_ROLES)
def get_worker(worker_id):
    return ok(public(fetch("workers", worker_id)))


# ------------------------------------------------------------------ LaborTask

ALLOWED = {
    "SCHEDULED": ("IN_PROGRESS", "CANCELLED", "NO_SHOW"),
    "IN_PROGRESS": ("COMPLETED", "CANCELLED"),
}

BUFFER = timedelta(minutes=const.WORKER_BUFFER_MINUTES)


def _double_booked(worker_id, window_start, window_end):
    """Each existing window is widened by the buffer on both sides and must not
    overlap the requested window by a positive duration. The buffer is applied
    once, not to both windows: a task starting exactly WORKER_BUFFER_MINUTES
    after another ends is accepted, twenty minutes after is a conflict."""
    for other in ordered("labor_tasks", lambda t: t["worker_id"] == worker_id):
        if other["status"] not in const.TASK_COMMITTED:
            continue
        other_lo = other["window_start"] - BUFFER
        other_hi = other["window_end"] + BUFFER
        if window_start < other_hi and other_lo < window_end:
            return True
    return False


@bp.post("/labor-tasks")
@guard([GROWER_MANAGER])
def create_task():
    payload = body()
    # priority 4
    zone_id = fields.string(payload, "zone_id")
    crop_cycle_id = fields.string(payload, "crop_cycle_id")
    worker_id = fields.string(payload, "worker_id")
    task_type = fields.enum_slot(payload, "task_type")
    window_start = fields.timestamp(payload, "window_start")
    window_end = fields.timestamp(payload, "window_end")
    planned_units = fields.number(payload, "planned_units", lo=0, exclusive_lo=True)
    standard = fields.number(
        payload, "standard_units_per_hour", lo=0, exclusive_lo=True
    )
    # priority 5
    fields.enum_value(task_type, "task_type", const.TASK_TYPES)
    # priority 7 - declared input order
    zone = fetch("zones", zone_id)
    cycle = fetch("crop_cycles", crop_cycle_id)
    worker = fetch("workers", worker_id)
    # the cycle-active gate outranks the safety gates
    if cycle["status"] not in const.CYCLE_ACTIVE_FOR_LABOR:
        raise ApiError("ERR_CROP_CYCLE_NOT_ACTIVE")
    # priority 13 then 14 - safety gates outrank everything below
    if zone["ipm_posture"] == "LOCKED":
        raise ApiError("ERR_ZONE_IPM_LOCKED")
    if zone["reentry_clear_at"] is not None and now() < zone["reentry_clear_at"]:
        raise ApiError("ERR_REENTRY_INTERVAL_ACTIVE")
    # priority 38
    if cycle["zone_id"] != zone_id:
        raise ApiError("ERR_CROP_CYCLE_ZONE_MISMATCH")
    # priority 35 - employment before skill
    if worker["status"] != "ACTIVE":
        raise ApiError("ERR_WORKER_INACTIVE")
    if worker["skill"] != task_type:
        raise ApiError("ERR_WORKER_SKILL_MISMATCH")
    # priority 28
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW")
    # priority 30
    if _double_booked(worker_id, window_start, window_end):
        raise ApiError("ERR_WORKER_DOUBLE_BOOKED")
    # unnumbered, immediately ahead of the fiscal gate
    if cycle["termination_date"] is not None:
        if window_start.date() > cycle["termination_date"]:
            raise ApiError("ERR_TASK_AFTER_TERMINATION")

    record = base_record()
    record.update({
        "zone_id": zone_id,
        "crop_cycle_id": crop_cycle_id,
        "worker_id": worker_id,
        "task_type": task_type,
        "window_start": window_start,
        "window_end": window_end,
        "planned_units": planned_units,
        "standard_units_per_hour": standard,
        "planned_hours": None,
        "planned_cost_usd": None,
        "actual_hours": None,
        "actual_units": None,
        "productivity_ratio": None,
        "bonus_usd": None,
        "actual_cost_usd": None,
        "status": "SCHEDULED",
        "cancel_reason": None,
    })
    calc.plan_labor_cost(record, worker)
    # priority 39 - the fiscal check is deliberately the final gate
    if D(zone["labor_budget_remaining_usd"]) < D(record["planned_cost_usd"]):
        raise ApiError("ERR_LABOR_BUDGET_EXCEEDED")

    db["labor_tasks"][record["id"]] = record
    calc.recompute_worker_hours(worker)
    calc.refresh_zone(zone, force=True)
    return created(public(record))


@bp.get("/labor-tasks")
@guard(ALL_ROLES)
def list_tasks():
    rows = ordered("labor_tasks")
    rows = filter_equals(rows, "zone_id", request.args.get("zone_id"))
    rows = filter_equals(rows, "crop_cycle_id", request.args.get("crop_cycle_id"))
    rows = filter_equals(rows, "worker_id", request.args.get("worker_id"))
    rows = filter_equals(rows, "task_type", request.args.get("task_type"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/labor-tasks/<task_id>")
@guard(ALL_ROLES)
def get_task(task_id):
    return ok(public(fetch("labor_tasks", task_id)))


@bp.post("/labor-tasks/<task_id>/transitions")
@guard([GROWER_MANAGER, HARVEST_SUPERVISOR])
def transition_task(task_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    actual_hours = None
    actual_units = None
    cancel_reason = None
    if target == "COMPLETED":
        actual_hours = fields.number(
            payload, "actual_hours", lo=0, exclusive_lo=True
        )
        actual_units = fields.number(
            payload, "actual_units", lo=0, exclusive_lo=True
        )
    if target in ("CANCELLED", "NO_SHOW"):
        cancel_reason = fields.string(payload, "cancel_reason", min_len=1)
    to_status_enum(target, const.TASK_STATUSES)
    task = fetch("labor_tasks", task_id)
    zone = db["zones"][task["zone_id"]]
    worker = db["workers"].get(task["worker_id"])
    terminal(task["status"], const.TASK_TERMINAL)
    transition(ALLOWED, task["status"], target)

    if target == "IN_PROGRESS":
        if zone["ipm_posture"] == "LOCKED":
            raise ApiError("ERR_ZONE_IPM_LOCKED")
        if zone["reentry_clear_at"] is not None and now() < zone["reentry_clear_at"]:
            raise ApiError("ERR_REENTRY_INTERVAL_ACTIVE")
        if now() < task["window_start"]:
            raise ApiError("ERR_TASK_WINDOW_NOT_OPEN")
        task["status"] = "IN_PROGRESS"
        touch(task)
        return ok(public(task))

    if target == "COMPLETED":
        calc.actual_labor_cost(task, worker, actual_hours, actual_units)
        task["status"] = "COMPLETED"
    elif target == "CANCELLED":
        task["cancel_reason"] = cancel_reason
        task["status"] = "CANCELLED"
    else:  # NO_SHOW
        if not now() > task["window_end"]:
            raise ApiError("ERR_TASK_WINDOW_STILL_OPEN")
        task["cancel_reason"] = cancel_reason
        task["status"] = "NO_SHOW"
    touch(task)
    if worker is not None:
        calc.recompute_worker_hours(worker)
    calc.refresh_zone(zone, force=True)
    return ok(public(task))
