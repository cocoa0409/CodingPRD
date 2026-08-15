"""Repair project endpoints (PRD 3.6)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_invalid_time_range,
    err_inspection_not_reported, err_insufficient_reserve,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, require_int, optional_int, require_datetime,
    parse_pagination, paginate, require_ref, optional_ref, get_project, public_view,
)

bp = Blueprint("repairs", __name__)


@bp.post("/ops/repair-projects")
def create_project():
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    insp_ref = optional_ref(payload, db.inspections, "inspection_id")
    inspection_id = insp_ref["id"] if insp_ref else None
    title = require_string(payload, "title")
    level_scope = require_string(payload, "level_scope")
    cost = require_int(payload, "estimated_cost_cents", minimum=0, exclusive_min=True)
    closed = optional_int(payload, "closed_space_count", default=0, minimum=0)
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "inspection_id": inspection_id,
        "title": title,
        "level_scope": level_scope,
        "estimated_cost_cents": cost,
        "closed_space_count": closed,
        "project_status": "PROPOSED",
        "funded_amount_cents": 0,
        "scheduled_start_at": None,
        "scheduled_end_at": None,
        "revision_count": 0,
    }
    db.stamp_new(ent)
    db.repair_projects[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/repair-projects/<repair_project_id>")
def get_project_route(repair_project_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_project(repair_project_id)))


@bp.get("/ops/repair-projects")
def list_projects():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.repair_projects.values())
    facility_id = request.args.get("facility_id")
    inspection_id = request.args.get("inspection_id")
    status = request.args.get("project_status")
    if facility_id is not None:
        items = [p for p in items if p["facility_id"] == facility_id]
    if inspection_id is not None:
        items = [p for p in items if p.get("inspection_id") == inspection_id]
    if status is not None:
        items = [p for p in items if p["project_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(p) for p in page], limit, offset, total)


@bp.post("/ops/repair-projects/<repair_project_id>/fund")
def fund_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    proj = get_project(repair_project_id)
    payload = body()
    amount = require_int(payload, "amount_cents", minimum=0, exclusive_min=True)
    if proj["project_status"] != "PROPOSED":
        raise err_invalid_state("only a PROPOSED project may be funded")
    if proj.get("inspection_id"):
        insp = db.inspections.get(proj["inspection_id"])
        if insp is None or insp["inspection_status"] != "REPORTED":
            raise err_inspection_not_reported()
    facility = db.facilities[proj["facility_id"]]
    if amount > facility["capital_reserve_cents"]:
        raise err_insufficient_reserve()
    proj["project_status"] = "FUNDED"
    proj["funded_amount_cents"] = amount
    db.touch(proj)
    facility["capital_reserve_cents"] -= amount
    db.touch_ledger(facility)
    return success_object(public_view(proj))


@bp.post("/ops/repair-projects/<repair_project_id>/schedule")
def schedule_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    proj = get_project(repair_project_id)
    payload = body()
    start_at = require_datetime(payload, "start_at")
    end_at = require_datetime(payload, "end_at")
    if proj["project_status"] != "FUNDED":
        raise err_invalid_state("only a FUNDED project may be scheduled")
    if end_at <= start_at:
        raise err_invalid_time_range()
    proj["project_status"] = "SCHEDULED"
    proj["scheduled_start_at"] = db.format_iso(start_at)
    proj["scheduled_end_at"] = db.format_iso(end_at)
    db.touch(proj)
    return success_object(public_view(proj))


@bp.post("/ops/repair-projects/<repair_project_id>/start")
def start_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    proj = get_project(repair_project_id)
    if proj["project_status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED project may start")
    proj["project_status"] = "IN_PROGRESS"
    db.touch(proj)
    facility = db.facilities[proj["facility_id"]]
    facility["closed_spaces"] += proj["closed_space_count"]
    db.touch(facility)  # version +1 per PRD 3.6
    return success_object(public_view(proj))


@bp.post("/ops/repair-projects/<repair_project_id>/close-out")
def close_out_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    proj = get_project(repair_project_id)
    if proj["project_status"] != "IN_PROGRESS":
        raise err_invalid_state("only an IN_PROGRESS project may close out")
    proj["project_status"] = "CLOSED_OUT"
    db.touch(proj)
    facility = db.facilities[proj["facility_id"]]
    facility["closed_spaces"] -= proj["closed_space_count"]
    db.touch(facility)  # version +1 per PRD 3.6 (compensating pair with start)
    return success_object(public_view(proj))


@bp.post("/ops/repair-projects/<repair_project_id>/defer")
def defer_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    proj = get_project(repair_project_id)
    payload = body()
    require_string(payload, "reason")
    if proj["project_status"] != "PROPOSED":
        raise err_invalid_state("only a PROPOSED project may be deferred")
    proj["project_status"] = "DEFERRED"
    db.touch(proj)
    return success_object(public_view(proj))


@bp.post("/ops/repair-projects/<repair_project_id>/revise")
def revise_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    proj = get_project(repair_project_id)
    payload = body()
    cost = optional_int(payload, "estimated_cost_cents", minimum=0, exclusive_min=True)
    if proj["project_status"] != "DEFERRED":
        raise err_invalid_state("only a DEFERRED project may be revised")
    if cost is not None:
        proj["estimated_cost_cents"] = cost
    proj["project_status"] = "PROPOSED"
    proj["revision_count"] += 1
    db.touch(proj)
    return success_object(public_view(proj))


@bp.post("/ops/repair-projects/<repair_project_id>/cancel")
def cancel_project(repair_project_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    proj = get_project(repair_project_id)
    if proj["project_status"] not in ("PROPOSED", "FUNDED", "DEFERRED"):
        raise err_invalid_state("only PROPOSED/FUNDED/DEFERRED projects may be cancelled")
    was_funded = proj["project_status"] == "FUNDED"
    proj["project_status"] = "CANCELLED"
    db.touch(proj)
    if was_funded and proj["funded_amount_cents"]:
        facility = db.facilities[proj["facility_id"]]
        facility["capital_reserve_cents"] += proj["funded_amount_cents"]
        db.touch_ledger(facility)
    return success_object(public_view(proj))
