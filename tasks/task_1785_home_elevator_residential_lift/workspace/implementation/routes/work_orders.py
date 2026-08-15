"""StructuralWorkOrder endpoints (PRD 3.4)."""

from flask import Blueprint, g

import db
from errors import (
    ApiError, ERR_CONTRACTOR_NOT_ACTIVE, ERR_CONTRACTOR_NOT_FOUND,
    ERR_CONTRACTOR_WINDOW_OVERLAP, ERR_INVALID_DATE_RANGE,
    ERR_NOT_ASSIGNED_CONTRACTOR, ERR_OPEN_WORK_ORDER_EXISTS,
    ERR_PROJECT_NOT_FOUND, ERR_PROJECT_STATE_FORBIDS,
    ERR_WORK_ORDER_NOT_FOUND, ERR_WORK_ORDER_STATE_FORBIDS, invalid_request,
    state_forbids,
)
from middleware import CONTRACTOR, PROJECT_COORDINATOR, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from services import calc
from util import get_json_body, serialize, validate_body

bp = Blueprint("work_orders", __name__)

CREATE_SPEC = {
    "project_id": ("string", True, None),
    "contractor_id": ("string", True, None),
    "scope_description": ("string", True, None),
    "scheduled_start_date": ("datetime", True, None),
    "scheduled_end_date": ("datetime", True, None),
    "estimated_cost": ("money", True, None),
}

NON_TERMINAL_WO = ("DRAFT", "RELEASED", "WORK_COMPLETE")


@bp.post("/api/work-orders")
@require_roles(PROJECT_COORDINATOR)
def create_work_order():
    vals = validate_body(get_json_body(), CREATE_SPEC)
    # body foreign keys (priority 4)
    project = get_or_404(db.projects, vals["project_id"], ERR_PROJECT_NOT_FOUND, "Project")
    get_or_404(db.contractors, vals["contractor_id"], ERR_CONTRACTOR_NOT_FOUND, "Contractor")
    # the named contractor must match the contractor recorded on the project
    if vals["contractor_id"] != project.get("contractor_id"):
        raise invalid_request("contractor_id must match the contractor recorded on the project")
    # creation-time cross-entity state gate (priority 5)
    if project["status"] != "PERMIT_APPROVED" or not project["requires_structural"]:
        raise state_forbids(ERR_PROJECT_STATE_FORBIDS, "Project")
    # uniqueness (priority 9): one non-terminal structural work order per project
    if any(w["project_id"] == project["id"] and w["status"] in NON_TERMINAL_WO for w in db.work_orders.values()):
        raise ApiError(ERR_OPEN_WORK_ORDER_EXISTS, 409, "Project already has a non-terminal structural work order")
    # temporal (priority 10)
    if vals["scheduled_end_date"] <= vals["scheduled_start_date"]:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422, "scheduled_end_date must be strictly after scheduled_start_date")
    rec = db.new_record({
        "project_id": project["id"],
        "contractor_id": vals["contractor_id"],
        "scope_description": vals["scope_description"],
        "scheduled_start_date": vals["scheduled_start_date"],
        "scheduled_end_date": vals["scheduled_end_date"],
        "estimated_cost": vals["estimated_cost"],
        "actual_cost": None,
        "rejection_reason": None,
        "status": "DRAFT",
    })
    db.work_orders[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/work-orders")
@require_roles(*ALL_ROLES)
def list_work_orders():
    return list_endpoint(db.work_orders, {
        "project_id": "project_id", "contractor_id": "contractor_id", "status": "status",
    })


@bp.get("/api/work-orders/<workOrderId>")
@require_roles(*ALL_ROLES)
def get_work_order(workOrderId):
    rec = get_or_404(db.work_orders, workOrderId, ERR_WORK_ORDER_NOT_FOUND, "WorkOrder")
    return ok(serialize(rec))


@bp.post("/api/work-orders/<workOrderId>/release")
@require_roles(PROJECT_COORDINATOR)
def release_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, ERR_WORK_ORDER_NOT_FOUND, "WorkOrder")
    if wo["status"] != "DRAFT":
        raise state_forbids(ERR_WORK_ORDER_STATE_FORBIDS, "WorkOrder")
    # referenced contractor must be ACTIVE (priority 8)
    contractor = db.contractors.get(wo["contractor_id"])
    if contractor is None or contractor["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACTOR_NOT_ACTIVE, 409, "Referenced contractor is SUSPENDED")
    # half-open window overlap vs this contractor's RELEASED / WORK_COMPLETE orders
    for other in db.work_orders.values():
        if other["id"] == wo["id"] or other["contractor_id"] != wo["contractor_id"]:
            continue
        if other["status"] not in ("RELEASED", "WORK_COMPLETE"):
            continue
        if calc.windows_overlap(
            wo["scheduled_start_date"], wo["scheduled_end_date"],
            other["scheduled_start_date"], other["scheduled_end_date"],
        ):
            raise ApiError(ERR_CONTRACTOR_WINDOW_OVERLAP, 409, "Window overlaps another released work order for this contractor")
    wo["status"] = "RELEASED"
    db.touch(wo)
    # side effect: project PERMIT_APPROVED -> STRUCTURAL_IN_PROGRESS
    project = db.projects.get(wo["project_id"])
    if project is not None and project["status"] == "PERMIT_APPROVED":
        project["status"] = "STRUCTURAL_IN_PROGRESS"
        db.touch(project)
    return ok(serialize(wo))


@bp.post("/api/work-orders/<workOrderId>/complete-work")
@require_roles(CONTRACTOR)
def complete_work(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, ERR_WORK_ORDER_NOT_FOUND, "WorkOrder")
    vals = validate_body(get_json_body(), {"actual_cost": ("money", True, None)})
    if wo["status"] != "RELEASED":
        raise state_forbids(ERR_WORK_ORDER_STATE_FORBIDS, "WorkOrder")
    # identity binding (priority 7): only the assigned contractor
    if g.user_id != wo["contractor_id"]:
        raise ApiError(ERR_NOT_ASSIGNED_CONTRACTOR, 403, "Caller is not the work order's contractor")
    wo["actual_cost"] = vals["actual_cost"]
    wo["status"] = "WORK_COMPLETE"
    db.touch(wo)
    return ok(serialize(wo))


@bp.post("/api/work-orders/<workOrderId>/verify")
@require_roles(PROJECT_COORDINATOR)
def verify_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, ERR_WORK_ORDER_NOT_FOUND, "WorkOrder")
    if wo["status"] != "WORK_COMPLETE":
        raise state_forbids(ERR_WORK_ORDER_STATE_FORBIDS, "WorkOrder")
    wo["status"] = "VERIFIED"
    db.touch(wo)
    # side effects: project -> READY_FOR_INSTALL; structural_adjustment computed
    project = db.projects.get(wo["project_id"])
    if project is not None:
        if project["status"] == "STRUCTURAL_IN_PROGRESS":
            project["status"] = "READY_FOR_INSTALL"
        project["structural_adjustment"] = calc.structural_adjustment(wo["actual_cost"], project["structural_estimate"])
        db.touch(project)
    return ok(serialize(wo))


@bp.post("/api/work-orders/<workOrderId>/reject-verification")
@require_roles(PROJECT_COORDINATOR)
def reject_verification(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, ERR_WORK_ORDER_NOT_FOUND, "WorkOrder")
    vals = validate_body(get_json_body(), {"rejection_reason": ("string", True, None)})
    if wo["status"] != "WORK_COMPLETE":
        raise state_forbids(ERR_WORK_ORDER_STATE_FORBIDS, "WorkOrder")
    # rework loop: back to RELEASED, actual cost cleared
    wo["rejection_reason"] = vals["rejection_reason"]
    wo["actual_cost"] = None
    wo["status"] = "RELEASED"
    db.touch(wo)
    return ok(serialize(wo))
