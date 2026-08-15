"""MachineAssignment endpoints.

Selector eligibility (PRD §3.2): recipe.target_yarn_count_ne must lie within the
machine's supported band -> ERR_COUNT_OUT_OF_RANGE otherwise. Window overlap per
PRD §2.9 half-open [start, end) -> ERR_WINDOW_CONFLICT.
"""

from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import (
    err_count_out_of_range,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_reference_not_found,
    err_window_conflict,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import serialize_machine_assignment
from services.calculations import actual_cost_per_lb, count_deviation_exceeds
from services.workflows import (
    components_of_recipe,
    machine_window_conflict,
    parse_instant,
    touch,
)
from validators import (
    apply_filters,
    get_json_body,
    get_pagination,
    req_string,
    sort_and_paginate,
)

bp = Blueprint("machine_assignments", __name__)

READ_ROLES = ("MillPlanner", "SpinningSupervisor", "MillAdmin")
WRITE_ROLE = "SpinningSupervisor"


def _get_assignment_or_404(aid):
    record = db.machine_assignments.get(aid)
    if record is None:
        raise err_not_found("Machine assignment not found")
    return record


@bp.post("/mill/machine-assignments")
def create_assignment():
    require_roles(WRITE_ROLE)
    body = get_json_body()
    machine_id = req_string(body, "machine_id")
    yarn_lot_id = req_string(body, "yarn_lot_id")
    window_start_raw = req_string(body, "window_start")
    window_end_raw = req_string(body, "window_end")

    # Reference existence (priority 4)
    machine = db.spinning_machines.get(machine_id)
    if machine is None:
        raise err_reference_not_found("machine_id does not resolve to an existing machine")
    yarn_lot = db.yarn_lots.get(yarn_lot_id)
    if yarn_lot is None:
        raise err_reference_not_found("yarn_lot_id does not resolve to an existing yarn lot")

    # Payload validity
    try:
        window_start = parse_instant(window_start_raw)
        window_end = parse_instant(window_end_raw)
    except ValueError:
        raise err_invalid_request("window_start and window_end must be ISO-8601 datetimes")
    if window_end <= window_start:
        raise err_invalid_request("window_end must fall strictly after window_start")

    # Selector eligibility: recipe target within machine band
    recipe = db.blend_recipes.get(yarn_lot["recipe_id"])
    if recipe is not None:
        target = recipe["target_yarn_count_ne"]
        if target < machine["supported_count_min_ne"] or target > machine["supported_count_max_ne"]:
            raise err_count_out_of_range("Recipe target yarn count outside the machine's supported range")

    # Temporal guard (§2.9)
    if machine_window_conflict(machine_id, window_start, window_end):
        raise err_window_conflict("Window overlaps another live assignment on this machine")

    ts = now_iso()
    record = {
        "id": new_id(),
        "machine_id": machine["id"],
        "yarn_lot_id": yarn_lot["id"],
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "status": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.machine_assignments[record["id"]] = record
    return success_object(serialize_machine_assignment(record), 201)


@bp.get("/mill/machine-assignments")
def list_assignments():
    require_roles(*READ_ROLES)
    limit, offset = get_pagination()
    items = apply_filters(
        list(db.machine_assignments.values()),
        {
            "machine_id": request.args.get("machine_id"),
            "yarn_lot_id": request.args.get("yarn_lot_id"),
            "status": request.args.get("status"),
        },
    )
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([serialize_machine_assignment(r) for r in page], limit, offset, total)


@bp.get("/mill/machine-assignments/<aid>")
def get_assignment(aid):
    require_roles(*READ_ROLES)
    return success_object(serialize_machine_assignment(_get_assignment_or_404(aid)))


@bp.post("/mill/machine-assignments/<aid>/start")
def start_assignment(aid):
    require_roles(WRITE_ROLE)
    record = _get_assignment_or_404(aid)
    if record["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED assignment can be started")
    machine = db.spinning_machines.get(record["machine_id"])
    if machine is None or machine["status"] != "ACTIVE":
        raise err_invalid_state("Machine must be ACTIVE to start an assignment")
    record["status"] = "IN_PROGRESS"
    touch(record)
    return success_object(serialize_machine_assignment(record))


@bp.post("/mill/machine-assignments/<aid>/complete")
def complete_assignment(aid):
    require_roles(WRITE_ROLE)
    record = _get_assignment_or_404(aid)
    if record["status"] != "IN_PROGRESS":
        raise err_invalid_state("Only an IN_PROGRESS assignment can be completed")

    yarn_lot = db.yarn_lots.get(record["yarn_lot_id"])
    if yarn_lot is not None:
        recipe = db.blend_recipes.get(yarn_lot["recipe_id"])
        comps = components_of_recipe(yarn_lot["recipe_id"]) if recipe is not None else []
        # Chronological actual cost (Variant B) — denominator is spun_weight_lbs
        yarn_lot["actual_cost_per_lb"] = actual_cost_per_lb(comps, db.fiber_lots, yarn_lot["spun_weight_lbs"])
        # Count-change detection
        if recipe is not None and count_deviation_exceeds(yarn_lot["actual_yarn_count_ne"], recipe["target_yarn_count_ne"]):
            yarn_lot["count_deviation_flag"] = True
        touch(yarn_lot)

    record["status"] = "COMPLETED"
    touch(record)
    return success_object(serialize_machine_assignment(record))


@bp.post("/mill/machine-assignments/<aid>/cancel")
def cancel_assignment(aid):
    require_roles(WRITE_ROLE)
    record = _get_assignment_or_404(aid)
    if record["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED assignment can be cancelled")
    record["status"] = "CANCELLED"
    touch(record)
    return success_object(serialize_machine_assignment(record))
