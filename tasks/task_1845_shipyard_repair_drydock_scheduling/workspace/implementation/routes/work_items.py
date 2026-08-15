"""WorkItem endpoints: base-spec lines, dependency graph, execution gates."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DEPENDENCY_CYCLE,
    ERR_DEPENDENCY_NOT_MET,
    ERR_HOT_WORK_PERMIT_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_PROJECT_NOT_IN_DOCK,
    ERR_SUBCONTRACTOR_CAPACITY,
    ERR_TRADE_MISMATCH,
)
from middleware import require_roles
from response import success_list, success_object
from services import project_ops
from services.project_ops import PRICING_MODES, MAX_SUBCONTRACTOR_IN_PROGRESS
from services.serializers import serialize_work_item, serialize_work_item_list
from util import (
    apply_filters,
    get_json_body,
    optional_bool,
    optional_int,
    optional_number,
    optional_str_array,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("work_items", __name__)

READ_ROLES = (
    "YardAdmin",
    "ProjectManager",
    "CommercialApprover",
    "ShipownerRep",
    "ClassSurveyor",
    "EnvironmentalOfficer",
    "Subcontractor",
)


def get_work_item_or_404(item_id: str) -> dict:
    item = db.work_items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, "WorkItem id does not exist")
    return item


def _pricing_types_from_body(body: dict) -> dict:
    """Rung-3 type checks for the pricing inputs (values may be absent)."""
    return {
        "quantity": optional_number(body, "quantity"),
        "unit_price_cents": optional_int(body, "unit_price_cents"),
        "estimated_hours": optional_number(body, "estimated_hours"),
        "hourly_rate_cents": optional_int(body, "hourly_rate_cents"),
        "materials_cost_cents": optional_int(body, "materials_cost_cents"),
    }


def _check_dep_targets_exist(project_id: str, dep_ids: list) -> None:
    """Rung 4: every depends_on_ids element must exist within the project."""
    for dep_id in dep_ids:
        dep = db.work_items.get(dep_id)
        if dep is None or dep["project_id"] != project_id:
            raise_err(ERR_NOT_FOUND, "depends_on_ids element does not exist in the project")


@bp.route("/v1/work-items", methods=["POST"])
@require_roles("ProjectManager")
def create_work_item(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness and field types.
    project_id = require_string(body, "project_id")
    description = require_string(body, "description")
    trade_code = require_string(body, "trade_code")
    pricing_mode = require_enum(body, "pricing_mode", PRICING_MODES)
    duration_days = require_int(body, "duration_days")
    if duration_days < 1:
        raise_err(ERR_INVALID_REQUEST, "duration_days must be >= 1")
    requires_hot_work = optional_bool(body, "requires_hot_work", False)
    depends_on_ids = optional_str_array(body, "depends_on_ids")
    if depends_on_ids is None:
        if "depends_on_ids" in body:
            raise_err(ERR_INVALID_REQUEST, "Field depends_on_ids must be an array of strings")
        depends_on_ids = []
    pricing = _pricing_types_from_body(body)

    # Rung 4: project and dependency targets exist.
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")
    _check_dep_targets_exist(project_id, depends_on_ids)

    # Rung 5: base-spec lines may only be added while DRAFT or BID_SUBMITTED.
    if project["status"] not in ("DRAFT", "BID_SUBMITTED"):
        raise_err(
            ERR_INVALID_STATE,
            "work lines may only be added while the project is DRAFT or BID_SUBMITTED",
        )

    # Rung 8: mode-conditional pricing inputs (base spec: no credit pricing).
    project_ops.validate_pricing_inputs(pricing_mode, pricing, allow_negative_unit_price=False)

    materials = pricing["materials_cost_cents"]
    materials_value = 0 if materials is None else materials
    item = {
        "project_id": project_id,
        "description": description,
        "trade_code": trade_code,
        "pricing_mode": pricing_mode,
        "quantity": pricing["quantity"],
        "unit_price_cents": pricing["unit_price_cents"],
        "estimated_hours": pricing["estimated_hours"],
        "hourly_rate_cents": pricing["hourly_rate_cents"],
        "materials_cost_cents": materials_value,
        "duration_days": duration_days,
        "depends_on_ids": list(depends_on_ids),
        "requires_hot_work": requires_hot_work,
        "subcontractor_id": None,
        "origin_kind": "BASE_SPEC",
        "origin_change_order_id": None,
        "line_total_cents": project_ops.price_line(
            pricing_mode,
            pricing["quantity"],
            pricing["unit_price_cents"],
            pricing["estimated_hours"],
            pricing["hourly_rate_cents"],
            materials_value,
        ),
        "status": "PLANNED",
        "completed_at_utc": None,
    }
    db.stamp_new(item)
    db.work_items[item["id"]] = item

    # Roll-ups: bid total and critical path recompute over the new graph.
    if project_ops.refresh_project_derived(project, include_bid=True):
        db.touch(project)
    return success_object(serialize_work_item(item), 201)


@bp.route("/v1/work-items", methods=["GET"])
@require_roles(*READ_ROLES)
def list_work_items(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.work_items.values()))
    items = apply_filters(items, ["project_id", "subcontractor_id", "origin_change_order_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_work_item_list(page), limit, offset, total)


@bp.route("/v1/work-items/<item_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_work_item(item_id: str, _user_id: str, _role: str):
    return success_object(serialize_work_item(get_work_item_or_404(item_id)))


@bp.route("/v1/work-items/<item_id>/dependents", methods=["GET"])
@require_roles(*READ_ROLES)
def list_dependents(item_id: str, _user_id: str, _role: str):
    get_work_item_or_404(item_id)
    limit, offset = parse_pagination()
    items = [
        w for w in db.work_items.values() if item_id in (w.get("depends_on_ids") or [])
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_work_item_list(page), limit, offset, total)


@bp.route("/v1/work-items/<item_id>", methods=["PATCH"])
@require_roles("ProjectManager")
def patch_work_item(item_id: str, _user_id: str, _role: str):
    item = get_work_item_or_404(item_id)
    body = get_json_body()

    # Rung 3: types of the editable fields.
    deps_provided = "depends_on_ids" in body
    sub_provided = "subcontractor_id" in body
    duration_provided = "duration_days" in body
    new_deps = None
    if deps_provided:
        if body["depends_on_ids"] is None:
            new_deps = []
        else:
            new_deps = optional_str_array(body, "depends_on_ids")
            if new_deps is None:
                raise_err(ERR_INVALID_REQUEST, "Field depends_on_ids must be an array of strings")
    new_sub = None
    if sub_provided:
        if body["subcontractor_id"] is not None and not isinstance(body["subcontractor_id"], str):
            raise_err(ERR_INVALID_REQUEST, "Field subcontractor_id must be a string")
        new_sub = body["subcontractor_id"]
    new_duration = None
    if duration_provided:
        new_duration = require_int(body, "duration_days")
        if new_duration < 1:
            raise_err(ERR_INVALID_REQUEST, "duration_days must be >= 1")

    # Rung 4: referenced ids exist.
    if new_deps is not None:
        _check_dep_targets_exist(item["project_id"], new_deps)
    if sub_provided and new_sub is not None and new_sub not in db.subcontractors:
        raise_err(ERR_NOT_FOUND, "Subcontractor id does not exist")

    # Rung 5: only a PLANNED line may be edited.
    if item["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "only a PLANNED work item may be edited")

    # Rung 8: dependency acyclicity, then trade certification.
    if new_deps is not None:
        if item_id in new_deps:
            raise_err(ERR_DEPENDENCY_CYCLE, "depends_on_ids must not reference the item itself")
        if project_ops.dependency_graph_has_cycle(item["project_id"], {item_id: new_deps}):
            raise_err(ERR_DEPENDENCY_CYCLE, "depends_on_ids would introduce a cycle")
    if sub_provided and new_sub is not None:
        sub = db.subcontractors[new_sub]
        if item["trade_code"] not in (sub.get("trade_codes") or []):
            raise_err(ERR_TRADE_MISMATCH, "subcontractor is not certified for the item's trade")

    schedule_affected = False
    if new_deps is not None and new_deps != item.get("depends_on_ids"):
        item["depends_on_ids"] = list(new_deps)
        schedule_affected = True
    if sub_provided and new_sub != item.get("subcontractor_id"):
        item["subcontractor_id"] = new_sub
    if duration_provided and new_duration != item.get("duration_days"):
        item["duration_days"] = new_duration
        schedule_affected = True

    db.touch(item)
    if schedule_affected:
        project = db.projects[item["project_id"]]
        if project_ops.refresh_project_derived(project, include_bid=False):
            db.touch(project)
    return success_object(serialize_work_item(item))


@bp.route("/v1/work-items/<item_id>/start", methods=["POST"])
@require_roles("ProjectManager", "Subcontractor")
def start_work_item(item_id: str, _user_id: str, _role: str):
    item = get_work_item_or_404(item_id)
    # Rung 5: transition defined only from PLANNED; parent project gate.
    if item["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "start requires a PLANNED work item")
    project = db.projects[item["project_id"]]
    in_dock_ok = project["status"] == "IN_DOCK"
    rework_ok = item["origin_kind"] == "WARRANTY_REWORK" and project["status"] == "DELIVERED"
    if not (in_dock_ok or rework_ok):
        raise_err(ERR_PROJECT_NOT_IN_DOCK, "parent project must be IN_DOCK to start work")
    # Rung 6: a subcontractor may only touch its own assignments.
    if _role == "Subcontractor" and item.get("subcontractor_id") is not None:
        if _user_id != item["subcontractor_id"]:
            raise_err(ERR_OWNERSHIP_MISMATCH, "work item is assigned to a different subcontractor")
    # Rung 7: hot-work permit gate.
    if item.get("requires_hot_work"):
        if not project_ops.hot_work_permit_covers(item["project_id"], db.clock_dt()):
            raise_err(
                ERR_HOT_WORK_PERMIT_REQUIRED,
                "no GRANTED HOT_WORK permit covers the current logical time",
            )
    # Rung 10: every dependency must be COMPLETE.
    for dep_id in item.get("depends_on_ids") or []:
        dep = db.work_items.get(dep_id)
        if dep is None or dep["status"] != "COMPLETE":
            raise_err(ERR_DEPENDENCY_NOT_MET, "a dependency is not COMPLETE")
    # Rung 11: crew loading — at most 3 IN_PROGRESS items per subcontractor.
    if item.get("subcontractor_id") is not None:
        in_progress = sum(
            1
            for w in db.work_items.values()
            if w.get("subcontractor_id") == item["subcontractor_id"] and w["status"] == "IN_PROGRESS"
        )
        if in_progress >= MAX_SUBCONTRACTOR_IN_PROGRESS:
            raise_err(ERR_SUBCONTRACTOR_CAPACITY, "subcontractor already holds 3 in-progress items")

    item["status"] = "IN_PROGRESS"
    db.touch(item)
    return success_object(serialize_work_item(item))


@bp.route("/v1/work-items/<item_id>/complete", methods=["POST"])
@require_roles("ProjectManager", "Subcontractor")
def complete_work_item(item_id: str, _user_id: str, _role: str):
    item = get_work_item_or_404(item_id)
    if item["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "complete requires an IN_PROGRESS work item")
    # Rung 6: the same ownership comparison as start.
    if _role == "Subcontractor" and item.get("subcontractor_id") is not None:
        if _user_id != item["subcontractor_id"]:
            raise_err(ERR_OWNERSHIP_MISMATCH, "work item is assigned to a different subcontractor")

    item["status"] = "COMPLETE"
    item["completed_at_utc"] = project_ops.logical_now_iso()
    db.touch(item)

    # A completed WARRANTY_REWORK line closes its claim.
    if item["origin_kind"] == "WARRANTY_REWORK":
        for claim in db.warranty_claims.values():
            if claim.get("rework_work_item_id") == item["id"] and claim["status"] == "ACCEPTED":
                claim["status"] = "CLOSED"
                db.touch(claim)

    # Completion gate re-evaluation plus schedule/provisional recomputation.
    project = db.projects[item["project_id"]]
    changed = project_ops.refresh_project_derived(project, include_bid=False)
    fired = project_ops.try_auto_complete_project(project)
    if changed or fired:
        db.touch(project)
    return success_object(serialize_work_item(item))


@bp.route("/v1/work-items/<item_id>/cancel", methods=["POST"])
@require_roles("ProjectManager")
def cancel_work_item(item_id: str, _user_id: str, _role: str):
    item = get_work_item_or_404(item_id)
    if item["status"] != "PLANNED" or item["origin_kind"] != "BASE_SPEC":
        raise_err(
            ERR_INVALID_STATE,
            "only a PLANNED base-spec work item may be cancelled",
        )
    item["status"] = "CANCELLED"
    db.touch(item)
    # The cancelled line leaves the bid roll-up and the critical path.
    project = db.projects[item["project_id"]]
    if project_ops.refresh_project_derived(project, include_bid=True):
        db.touch(project)
    return success_object(serialize_work_item(item))
