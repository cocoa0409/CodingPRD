"""ExpirationTask endpoints."""

from flask import Blueprint, request

import calc
import clock
from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_err,
)
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, page, parse_pagination,
    req_enum, req_int, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object

bp = Blueprint("tasks", __name__)

TASK_TYPES = ("NOTICE_DEADLINE", "DATA_PREP", "SUNSET_COMMUNICATION", "STRIKE_CONTINGENCY", "BUDGET_REOPENER")
TASK_STATUSES = ("PENDING", "IN_PROGRESS", "DONE", "MISSED")


@bp.post("/labor-relations/expiration-tasks")
def create_task():
    authenticate(["LRManager", "Negotiator"])
    body = get_body()
    agreement_id = req_string(body, "agreement_id")
    title = req_string(body, "title")
    task_type = req_enum(body, "task_type", TASK_TYPES)
    due_offset_days = req_int(body, "due_offset_days")
    assignee_user_id = req_string(body, "assignee_user_id")

    agreement = lookup(db.agreements, agreement_id, "CollectiveAgreement")
    if agreement["status"] not in ("ACTIVE", "EXPIRED", "EXTENDED"):
        raise_err(ERR_INVALID_STATE,
                  "Tasks can only be created against ACTIVE, EXPIRED, or EXTENDED agreements")

    task = new_entity()
    task.update({
        "agreement_id": agreement_id,
        "title": title,
        "task_type": task_type,
        "due_offset_days": due_offset_days,
        "due_date": calc.task_due_date(agreement["expiration_date"], due_offset_days),
        "assignee_user_id": assignee_user_id,
        "status": "PENDING",
        "completed_late": False,
    })
    db.tasks[task["id"]] = task
    return success_object(serialize(task), status=201)


@bp.get("/labor-relations/expiration-tasks")
def list_tasks():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    task_type = request.args.get("task_type")
    items = list(db.tasks.values())
    if agreement_id is not None:
        items = [t for t in items if t["agreement_id"] == agreement_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if task_type is not None:
        items = [t for t in items if t["task_type"] == task_type]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(t) for t in slice_], limit, offset, total)


@bp.get("/labor-relations/expiration-tasks/<task_id>")
def get_task(task_id):
    authenticate(ALL_ROLES)
    task = lookup(db.tasks, task_id, "ExpirationTask")
    return success_object(serialize(task))


@bp.post("/labor-relations/expiration-tasks/<task_id>/state")
def transition_task(task_id):
    authenticate(["LRManager", "Negotiator"])
    task = lookup(db.tasks, task_id, "ExpirationTask")
    body = get_body()
    to_status = req_string(body, "to_status")
    if to_status not in TASK_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "Unknown expiration-task status: %s" % to_status)

    if to_status == "IN_PROGRESS":
        if task["status"] != "PENDING":
            raise_err(ERR_INVALID_STATE, "Only a PENDING task can enter IN_PROGRESS")
        task["status"] = "IN_PROGRESS"

    elif to_status == "DONE":
        if task["status"] not in ("PENDING", "IN_PROGRESS", "MISSED"):
            raise_err(ERR_INVALID_STATE, "Only a PENDING, IN_PROGRESS, or MISSED task can be done")
        task["completed_late"] = (clock.now() > task["due_date"]) or (task["status"] == "MISSED")
        task["status"] = "DONE"

    else:
        # PENDING / MISSED are not settable through this endpoint
        raise_err(ERR_INVALID_STATE, "Cannot transition a task to %s via this endpoint" % to_status)

    touch(task)
    return success_object(serialize(task))
