"""EvsTask turnover state machine: create, assign, start, complete, cancel.

List ordering overrides the default: priority_score DESC then requested_at ASC.
"""

from flask import Blueprint, request

import errors
from errors import err
from db import store, iso
from middleware import authenticate, authorize, get_json_body, parse_pagination
from response import success, list_success
from services import common
from services.listing import paginate

bp = Blueprint("evs_tasks", __name__)

TASK_TYPES = {"STAT", "ISOLATION", "ROUTINE"}
TASK_STATUSES = {"REQUESTED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
NON_TERMINAL = {"REQUESTED", "ASSIGNED", "IN_PROGRESS"}


def _get_task_or_404(task_id):
    task = store.evs_tasks.get(task_id)
    if task is None:
        raise err(errors.ERR_NOT_FOUND, "EVS task not found")
    return task


@bp.route("/evs-tasks", methods=["POST"])
def create_task():
    user_id, role = authenticate()
    authorize(role, {"ChargeNurse", "BedControlCoordinator", "EvsTech"})
    body = get_json_body()

    bed_id = body.get("bed_id")
    if not isinstance(bed_id, str) or not bed_id:
        raise err(errors.ERR_INVALID_REQUEST, "bed_id is required")
    bed = store.beds.get(bed_id)
    if bed is None:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "bed_id does not resolve")

    task_type = body.get("task_type", "ROUTINE")
    if task_type is None:
        task_type = "ROUTINE"
    if task_type not in TASK_TYPES:
        raise err(errors.ERR_INVALID_REQUEST, "task_type must be STAT, ISOLATION, or ROUTINE")

    # business: bed must be DIRTY
    if bed["status"] != "DIRTY":
        raise err(errors.ERR_BED_NOT_DIRTY, "Bed is not DIRTY")
    # business: at most one non-terminal task per bed
    for t in store.evs_tasks.values():
        if t["bed_id"] == bed_id and t["status"] in NON_TERMINAL:
            raise err(errors.ERR_EVS_TASK_EXISTS, "Bed already has a non-terminal EVS task")

    now = store.clock_now()
    task = {
        "bed_id": bed_id,
        "task_type": task_type,
        "status": "REQUESTED",
        "assigned_tech_id": None,
        "requested_at": iso(now),
        "priority_score": 0,
        "_requested_dt": now,
    }
    common.stamp_new(task)
    common.recompute_evs_task(task)
    store.evs_tasks[task["id"]] = task
    return success(common.serialize_evs_task(task), status=201)


@bp.route("/evs-tasks/<task_id>", methods=["GET"])
def get_task(task_id):
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "EvsTech", "ChargeNurse", "BedControlCoordinator"})
    task = _get_task_or_404(task_id)
    return success(common.serialize_evs_task(task))


@bp.route("/evs-tasks", methods=["GET"])
def list_tasks():
    _, role = authenticate()
    authorize(role, {"FlowAdmin", "EvsTech", "ChargeNurse", "BedControlCoordinator"})
    limit, offset = parse_pagination()
    bed_filter = request.args.get("bed_id")
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in TASK_STATUSES:
        raise err(errors.ERR_INVALID_REQUEST, "invalid status filter")
    tasks = list(store.evs_tasks.values())
    if bed_filter is not None:
        tasks = [t for t in tasks if t["bed_id"] == bed_filter]
    if status_filter is not None:
        tasks = [t for t in tasks if t["status"] == status_filter]
    # recompute scores before ordering
    for t in tasks:
        common.recompute_evs_task(t)
    # order by priority_score DESC, requested_at ASC (via _requested_dt)
    sort_key = lambda t: (-t["priority_score"], t["_requested_dt"])
    page, total = paginate(tasks, limit, offset, sort_key=sort_key)
    return list_success([common.serialize_evs_task(t) for t in page], limit, offset, total)


@bp.route("/evs-tasks/<task_id>/assign", methods=["POST"])
def assign_task(task_id):
    user_id, role = authenticate()
    authorize(role, {"EvsTech", "FlowAdmin"})
    task = _get_task_or_404(task_id)
    body = get_json_body()
    if task["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "EVS task is not REQUESTED")
    if role == "FlowAdmin":
        tech_id = body.get("tech_id")
        task["assigned_tech_id"] = tech_id if tech_id is not None else user_id
    else:
        task["assigned_tech_id"] = user_id
    task["status"] = "ASSIGNED"
    common.touch(task)
    return success(common.serialize_evs_task(task))


@bp.route("/evs-tasks/<task_id>/start", methods=["POST"])
def start_task(task_id):
    _, role = authenticate()
    authorize(role, {"EvsTech"})
    task = _get_task_or_404(task_id)
    if task["status"] != "ASSIGNED":
        raise err(errors.ERR_INVALID_STATE, "EVS task is not ASSIGNED")
    task["status"] = "IN_PROGRESS"
    common.touch(task)
    return success(common.serialize_evs_task(task))


@bp.route("/evs-tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    _, role = authenticate()
    authorize(role, {"EvsTech"})
    task = _get_task_or_404(task_id)
    if task["status"] != "IN_PROGRESS":
        raise err(errors.ERR_INVALID_STATE, "EVS task is not IN_PROGRESS")
    bed = store.beds.get(task["bed_id"])
    if bed is None or bed["status"] != "DIRTY":
        raise err(errors.ERR_INVALID_STATE, "Target bed is not DIRTY")
    task["status"] = "COMPLETED"
    common.touch(task)
    # bed DIRTY -> CLEAN (cohort preserved)
    bed["status"] = "CLEAN"
    common.touch(bed)
    unit = store.units.get(bed["unit_id"])
    if unit is not None:
        common.recompute_unit(unit)
    return success(common.serialize_evs_task(task))


@bp.route("/evs-tasks/<task_id>/cancel", methods=["POST"])
def cancel_task(task_id):
    _, role = authenticate()
    authorize(role, {"EvsTech", "ChargeNurse", "FlowAdmin"})
    task = _get_task_or_404(task_id)
    if task["status"] == "IN_PROGRESS":
        # IN_PROGRESS may be cancelled only by ChargeNurse or FlowAdmin.
        if role not in ("ChargeNurse", "FlowAdmin"):
            raise err(errors.ERR_FORBIDDEN, "Only ChargeNurse or FlowAdmin may cancel an IN_PROGRESS task")
    elif task["status"] not in ("REQUESTED", "ASSIGNED"):
        raise err(errors.ERR_INVALID_STATE, "EVS task cannot be cancelled from this state")
    task["status"] = "CANCELLED"
    common.touch(task)
    return success(common.serialize_evs_task(task))
