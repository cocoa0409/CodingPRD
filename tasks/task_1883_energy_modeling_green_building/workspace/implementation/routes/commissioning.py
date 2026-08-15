"""CommissioningTask endpoints (PRD 3.6)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import (
    check_cx_overlap,
    get_member,
    get_project,
    get_task,
    locked_model,
    ser_task,
    sorted_created,
    stamp,
    touch,
)
from util import (
    CX_OUTCOMES,
    TASK_TYPES,
    as_bool,
    as_dt,
    as_enum,
    as_str,
    body,
    pagination_args,
    parse_dt,
    required,
)

bp = Blueprint("commissioning", __name__)


@bp.post("/commissioning-tasks")
def create_task():
    _user_id, role = auth_headers()
    data = body()
    project_id = as_str(required(data, "project_id"), "project_id")
    task_type = as_enum(required(data, "task_type"), TASK_TYPES, "task_type")
    agent_id = as_str(required(data, "agent_id"), "agent_id")
    scheduled_start = as_dt(required(data, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(required(data, "scheduled_end"), "scheduled_end")
    start_dt = parse_dt(scheduled_start)
    end_dt = parse_dt(scheduled_end)
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "scheduled_end must be later than scheduled_start"
        )
    is_prerequisite_linked = as_bool(
        required(data, "is_prerequisite_linked"), "is_prerequisite_linked"
    )
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    agent = get_member(agent_id)
    # Compliance gate (stage 8): independence precedes the specialty check.
    locked_proposed = locked_model(project["id"], "PROPOSED")
    if not agent["is_independent"] or (
        locked_proposed is not None and locked_proposed["created_by"] == agent["id"]
    ):
        raise ApiError(
            "ERR_CX_AGENT_NOT_INDEPENDENT",
            403,
            "Commissioning agent must be independent of design work",
        )
    # Referential attribute check (stage 9).
    if agent["specialty"] != "COMMISSIONING":
        raise ApiError(
            "ERR_INVALID_TEAM_MEMBER_SPECIALTY",
            422,
            "commissioning agent must have specialty COMMISSIONING",
        )
    # Structural constraint (stage 10): half-open overlap.
    check_cx_overlap(project["id"], start_dt, end_dt)
    rec = stamp(
        {
            "project_id": project["id"],
            "task_type": task_type,
            "agent_id": agent["id"],
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "is_prerequisite_linked": is_prerequisite_linked,
            "outcome": None,
            "result_notes": None,
            "status": "SCHEDULED",
        }
    )
    DB["commissioning_tasks"][rec["id"]] = rec
    return ok(ser_task(rec), status=201)


@bp.get("/commissioning-tasks")
def list_tasks():
    auth_headers()
    items = list(DB["commissioning_tasks"].values())
    project_id = request.args.get("project_id")
    agent_id = request.args.get("agent_id")
    status = request.args.get("status")
    if project_id is not None:
        items = [t for t in items if t["project_id"] == project_id]
    if agent_id is not None:
        items = [t for t in items if t["agent_id"] == agent_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_task(t) for t in page], total, limit, offset)


@bp.get("/commissioning-tasks/<task_id>")
def get_one_task(task_id):
    auth_headers()
    return ok(ser_task(get_task(task_id)))


@bp.post("/commissioning-tasks/<task_id>/start")
def start_task(task_id):
    user_id, role = auth_headers()
    body()
    require_role(role, {"CommissioningAgent"})
    task = get_task(task_id)
    if user_id != task["agent_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_COMMISSIONING_AGENT",
            403,
            "Only the assigned agent may start the task",
        )
    if task["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TASK_STATE", 409, "start requires SCHEDULED")
    task["status"] = "IN_PROGRESS"
    touch(task)
    return ok(ser_task(task))


@bp.post("/commissioning-tasks/<task_id>/complete")
def complete_task(task_id):
    user_id, role = auth_headers()
    data = body()
    outcome = as_enum(required(data, "outcome"), CX_OUTCOMES, "outcome")
    result_notes = None
    if "result_notes" in data and data["result_notes"] is not None:
        result_notes = as_str(data["result_notes"], "result_notes")
    require_role(role, {"CommissioningAgent"})
    task = get_task(task_id)
    if user_id != task["agent_id"]:
        raise ApiError(
            "ERR_NOT_ASSIGNED_COMMISSIONING_AGENT",
            403,
            "Only the assigned agent may complete the task",
        )
    if task["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_TASK_STATE", 409, "complete requires IN_PROGRESS")
    task["outcome"] = outcome
    task["result_notes"] = result_notes
    task["status"] = outcome
    touch(task)
    return ok(ser_task(task))
