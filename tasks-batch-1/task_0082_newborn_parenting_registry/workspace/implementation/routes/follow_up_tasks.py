"""FollowUpTask resource (PRD §3.9). Tasks are spawned at discharge."""

from flask import Blueprint, request

import db
import services
from errors import invalid_state, not_found
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("follow_up_tasks", __name__)

TASK_STATUSES = {"OPEN", "ATTEMPTED", "COMPLETED", "ESCALATED", "MISSED", "CANCELLED"}
TASK_TYPES = {"WEIGHT_CHECK", "JAUNDICE_CHECK", "FEEDING_CHECK", "SAFETY_CALL"}


def _get_task(task_id):
    t = db.follow_up_tasks.get(task_id)
    if t is None:
        raise not_found("Follow-up task not found.")
    return t


@bp.get("/follow-up-tasks/<task_id>")
def get_task(task_id):
    require_roles("AttendingNurse", "RegistrySupervisor")
    return ok_object(db.public(_get_task(task_id)))


@bp.get("/follow-up-tasks")
def list_tasks():
    require_roles("AttendingNurse", "RegistrySupervisor")
    limit, offset = parse_pagination()
    newborn_id = request.args.get("newborn_id")
    status = request.args.get("status")
    task_type = request.args.get("task_type")
    rows = list(db.follow_up_tasks.values())
    if newborn_id is not None:
        rows = [r for r in rows if r["newborn_id"] == newborn_id]
    if status is not None:
        require_enum(status, "status", TASK_STATUSES)
        rows = [r for r in rows if r["status"] == status]
    if task_type is not None:
        require_enum(task_type, "task_type", TASK_TYPES)
        rows = [r for r in rows if r["task_type"] == task_type]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/follow-up-tasks/<task_id>/record-attempt")
def record_attempt(task_id):
    require_roles("AttendingNurse")
    t = _get_task(task_id)
    body = get_body()
    scheduled_at = optional_field(body, "scheduled_at", str, default=None)
    if t["status"] not in ("OPEN", "ATTEMPTED"):
        raise invalid_state("Record-attempt requires status OPEN or ATTEMPTED.")
    t["attempt_count"] = int(t["attempt_count"]) + 1
    if scheduled_at is not None:
        t["scheduled_at"] = scheduled_at
    if t["attempt_count"] >= 3:
        t["status"] = "ESCALATED"
        db.stamp_update(t)
        services.append_audit("FOLLOWUP_ESCALATED", request.headers.get("X-User-Role"),
                              t["newborn_id"], {"follow_up_task_id": task_id})
    else:
        t["status"] = "ATTEMPTED"
        db.stamp_update(t)
    return ok_object(db.public(t))


@bp.post("/follow-up-tasks/<task_id>/complete")
def complete_task(task_id):
    require_roles("AttendingNurse")
    t = _get_task(task_id)
    if t["status"] not in ("OPEN", "ATTEMPTED"):
        raise invalid_state("Complete requires status OPEN or ATTEMPTED.")
    t["status"] = "COMPLETED"
    db.stamp_update(t)
    return ok_object(db.public(t))


@bp.post("/follow-up-tasks/<task_id>/mark-missed")
def mark_missed(task_id):
    require_roles("AttendingNurse")
    t = _get_task(task_id)
    if t["status"] not in ("OPEN", "ATTEMPTED"):
        raise invalid_state("Mark-missed requires status OPEN or ATTEMPTED.")
    now_dt = db.current_utc_dt()
    if not (now_dt > db.parse_iso(t["due_at"])):
        raise invalid_state("Task may only be marked missed once the clock is past due_at.")
    t["status"] = "MISSED"
    db.stamp_update(t)
    return ok_object(db.public(t))
