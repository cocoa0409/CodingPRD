from flask import Blueprint, request
from auth import require_role
from db import db, bump
from envelope import success
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_INPUT, ERR_FORBIDDEN,
    ERR_NO_PENDING_TASKS, ERR_TICKET_UNRESOLVED,
)
from validation import need_body, optional_bool, require_enum, occ_check
from serializers import serialize_operator_task
from services.priority import compute_priority_score

bp = Blueprint("operator_tasks", __name__)

VALID_CITIES = {"BJ", "SH"}


@bp.post("/operator-tasks/auto-assign")
def auto_assign():
    uid, _ = require_role({"Operator"})
    body = need_body(request.get_json(silent=True))
    city_code = require_enum(body, "city_code", VALID_CITIES)

    candidates = []
    for task in db.operator_tasks.values():
        if task["status"] != "PENDING":
            continue
        cab = db.cabinets.get(task["cabinet_id"])
        if cab is None or cab["city_code"] != city_code:
            continue
        # Recompute priority score on each call.
        task["priority_score"] = compute_priority_score(task["cabinet_id"])
        candidates.append(task)

    if not candidates:
        raise APIError(ERR_NO_PENDING_TASKS, 409, "No pending tasks for city")

    candidates.sort(key=lambda t: (-t["priority_score"], t["created_at"]))
    winner = candidates[0]
    winner["assigned_operator_id"] = uid
    winner["status"] = "ASSIGNED"
    bump(winner)
    return success(serialize_operator_task(winner))


@bp.get("/operator-tasks/<task_id>")
def get_task(task_id):
    require_role({"Admin", "Operator"})
    t = db.operator_tasks.get(task_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Operator task not found")
    return success(serialize_operator_task(t))


@bp.post("/operator-tasks/<task_id>/complete")
def complete_task(task_id):
    uid, role = require_role({"Operator", "Admin"})
    t = db.operator_tasks.get(task_id)
    if t is None:
        raise APIError(ERR_NOT_FOUND, 404, "Operator task not found")

    body = request.get_json(silent=True) or {}
    if body:
        occ_check(t, body)
    cancel = optional_bool(body, "cancel") if body else None

    if cancel is True:
        if role != "Admin":
            raise APIError(ERR_FORBIDDEN, 403, "Only Admin may cancel a task")
        if t["status"] != "PENDING":
            raise APIError(ERR_INVALID_STATE, 409, "Cancel only valid from PENDING")
        t["status"] = "CANCELLED"
        bump(t)
        return success(serialize_operator_task(t))

    # Auto-transition ASSIGNED→IN_PROGRESS on first complete.
    if t["status"] == "ASSIGNED":
        t["status"] = "IN_PROGRESS"
    if t["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, 409, "Task is not IN_PROGRESS")

    if t["task_type"] == "REPAIR_DISPATCH":
        linked = db.repair_tickets.get(t.get("linked_repair_ticket_id"))
        if linked is None or linked["status"] != "RESOLVED":
            raise APIError(ERR_TICKET_UNRESOLVED, 409, "Linked repair ticket is not resolved")

    t["status"] = "COMPLETED"
    bump(t)
    return success(serialize_operator_task(t))
