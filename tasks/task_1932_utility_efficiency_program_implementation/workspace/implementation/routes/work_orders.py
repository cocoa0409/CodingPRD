"""Work order endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404
from services import core

bp = Blueprint("work_orders", __name__)


@bp.get("/efficiency/work_orders")
def list_work_orders():
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    items = list(db.work_orders.values())
    project_id = request.args.get("project_id")
    contractor_id = request.args.get("contractor_id")
    status = request.args.get("status")
    if project_id is not None:
        items = [w for w in items if w.get("project_id") == project_id]
    if contractor_id is not None:
        items = [w for w in items if w.get("contractor_id") == contractor_id]
    if status is not None:
        items = [w for w in items if w.get("status") == status]
    return paginate(items)


@bp.get("/efficiency/work_orders/<work_order_id>")
def get_work_order(work_order_id):
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    return success_object(fetch_or_404(db.work_orders, work_order_id, "WorkOrder"))


@bp.post("/efficiency/work_orders/<work_order_id>/schedule")
def schedule_work_order(work_order_id):
    role, user_id = require_roles({"Contractor"})
    wo = fetch_or_404(db.work_orders, work_order_id, "WorkOrder")
    if wo["status"] != "DRAFT":
        raise errors.invalid_state(f"WorkOrder in {wo['status']} cannot be scheduled")
    if wo.get("contractor_id") != user_id:
        raise errors.not_resource_owner()
    if not wo.get("direct_install"):
        if core.has_calendar_conflict(wo["contractor_id"], wo["scheduled_on"], wo.get("duration_hours") or 0, exclude_wo_id=wo["id"]):
            raise errors.schedule_conflict()
    wo["status"] = "SCHEDULED"
    db.touch(wo)
    return success_object(wo)


@bp.post("/efficiency/work_orders/<work_order_id>/start")
def start_work_order(work_order_id):
    role, user_id = require_roles({"Contractor"})
    wo = fetch_or_404(db.work_orders, work_order_id, "WorkOrder")
    if wo["status"] != "SCHEDULED":
        raise errors.invalid_state(f"WorkOrder in {wo['status']} cannot be started")
    if wo.get("contractor_id") != user_id:
        raise errors.not_resource_owner()
    # Current clock date must equal scheduled_on date
    scheduled_date = db.parse_dt(wo["scheduled_on"]).date()
    clock_date = db.get_clock().date()
    if clock_date < scheduled_date:
        raise errors.start_too_early()
    if clock_date != scheduled_date:
        # PRD: "the logical clock's calendar date must equal the scheduled_on date"
        raise errors.start_too_early("Current clock date does not equal scheduled_on date")
    wo["status"] = "IN_PROGRESS"
    db.touch(wo)
    return success_object(wo)


@bp.post("/efficiency/work_orders/<work_order_id>/complete")
def complete_work_order(work_order_id):
    role, user_id = require_roles({"Contractor"})
    wo = fetch_or_404(db.work_orders, work_order_id, "WorkOrder")

    # State (priority 5)
    if wo["status"] != "IN_PROGRESS":
        raise errors.invalid_state(f"WorkOrder in {wo['status']} cannot be completed")

    # Segregation-of-duties screen against the inspector pool (priority 7)
    pool = []
    for insp in db.inspectors.values():
        if insp.get("status") != "ACTIVE":
            continue
        if wo.get("contractor_id") in (insp.get("excluded_contractor_ids") or []):
            continue
        pool.append(insp)

    # Ownership (priority 10)
    if wo.get("contractor_id") != user_id:
        raise errors.not_resource_owner()

    # Inspector availability (priority 13)
    if not pool:
        raise errors.no_inspector_available()

    # Rank by earliest created_at
    pool.sort(key=lambda i: (i.get("created_at") or "", i.get("id") or ""))
    chosen = pool[0]

    wo["completed_on"] = db.now_iso()
    wo["assigned_inspector_id"] = chosen["id"]
    wo["status"] = "COMPLETED"
    db.touch(wo)

    contractor = db.contractors.get(wo["contractor_id"])
    if contractor is not None:
        core.recompute_install_counts(contractor)

    project = db.projects.get(wo["project_id"])
    if project is not None and project.get("status") == "SCHEDULED":
        project["status"] = "INSTALLED"
        db.touch(project)

    return success_object(wo)


@bp.post("/efficiency/work_orders/<work_order_id>/cancel")
def cancel_work_order(work_order_id):
    role, user_id = require_roles({"Contractor"})
    wo = fetch_or_404(db.work_orders, work_order_id, "WorkOrder")
    if wo["status"] not in ("DRAFT", "SCHEDULED"):
        raise errors.invalid_state(f"WorkOrder in {wo['status']} cannot be cancelled")
    if wo.get("contractor_id") != user_id:
        raise errors.not_resource_owner()
    wo["status"] = "CANCELLED"
    db.touch(wo)
    return success_object(wo)
