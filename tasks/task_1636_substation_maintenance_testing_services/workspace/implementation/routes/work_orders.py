"""WorkOrder endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_not_found, err_state_transition, err_segregation_of_duties,
    err_stale_version, err_outage_capacity_exceeded,
)
from services.common import (
    body, require_string, require_number, parse_pagination, paginate,
    get_defect, get_work_order, get_outage_window, get_technician,
)
from services.calculations import compute_cost_rollup, refresh_asset_condition_and_due

bp = Blueprint("work_orders", __name__)


def work_order_view(w):
    return {
        "id": w["id"],
        "defect_id": w["defect_id"],
        "asset_id": w["asset_id"],
        "outage_window_id": w.get("outage_window_id"),
        "assigned_technician_id": w["assigned_technician_id"],
        "title": w["title"],
        "estimated_hours": w["estimated_hours"],
        "status": w["status"],
        "labor_lines": w.get("labor_lines", []),
        "parts_lines": w.get("parts_lines", []),
        "cost_subtotal": w.get("cost_subtotal"),
        "mobilization_fee": w.get("mobilization_fee"),
        "total_cost": w.get("total_cost"),
        "completed_at": w.get("completed_at"),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.post("/work-orders")
def create_work_order():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    defect_id = require_string(payload, "defect_id")
    assigned_technician_id = require_string(payload, "assigned_technician_id")
    title = require_string(payload, "title")
    estimated_hours = require_number(payload, "estimated_hours")
    if estimated_hours <= 0:
        raise err_validation("estimated_hours must be > 0")

    # FK checks
    defect = get_defect(defect_id)
    get_technician(assigned_technician_id)

    if defect["status"] != "OPEN":
        raise err_state_transition("Defect is not OPEN")

    ent = {
        "id": db.new_id(),
        "defect_id": defect_id,
        "asset_id": defect["asset_id"],
        "outage_window_id": None,
        "assigned_technician_id": assigned_technician_id,
        "title": title,
        "estimated_hours": estimated_hours,
        "status": "DRAFT",
        "labor_lines": [],
        "parts_lines": [],
        "cost_subtotal": None,
        "mobilization_fee": None,
        "total_cost": None,
        "completed_at": None,
    }
    db.stamp_new(ent)
    db.work_orders[ent["id"]] = ent

    # Defect OPEN -> WORK_ORDERED
    defect["status"] = "WORK_ORDERED"
    db.touch(defect)

    return success_object(work_order_view(ent), status=201)


@bp.get("/work-orders")
def list_work_orders():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.work_orders.values())
    defect_id = request.args.get("defect_id")
    if defect_id:
        items = [w for w in items if w["defect_id"] == defect_id]
    asset_id = request.args.get("asset_id")
    if asset_id:
        items = [w for w in items if w["asset_id"] == asset_id]
    outage_window_id = request.args.get("outage_window_id")
    if outage_window_id:
        items = [w for w in items if w.get("outage_window_id") == outage_window_id]
    assigned_technician_id = request.args.get("assigned_technician_id")
    if assigned_technician_id:
        items = [w for w in items if w["assigned_technician_id"] == assigned_technician_id]
    status = request.args.get("status")
    if status:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)


@bp.get("/work-orders/<id>")
def get_work_order_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    w = get_work_order(id)
    return success_object(work_order_view(w))


@bp.post("/work-orders/<id>/schedule")
def schedule_work_order(id):
    actor = get_actor()
    require_roles(actor, ["OutageCoordinator"])
    wo = get_work_order(id)
    payload = body()
    outage_window_id = require_string(payload, "outage_window_id")
    expected_outage_window_version = payload.get("expected_outage_window_version")

    # FK: window must exist
    window = get_outage_window(outage_window_id)

    # State check
    if wo["status"] != "DRAFT":
        raise err_state_transition("Work order is not DRAFT")
    if window["status"] not in ("APPROVED", "SWITCHING", "CLEARED"):
        raise err_state_transition("Window is not APPROVED, SWITCHING, or CLEARED")

    # OCC check
    if expected_outage_window_version is not None:
        if expected_outage_window_version != window["version"]:
            raise err_stale_version()

    # Cross-reference: window.asset_id == wo.asset_id
    if window["asset_id"] != wo["asset_id"]:
        raise err_validation("Window asset does not match work order asset")

    # Capacity check
    remaining = window["duration_hours"] - window.get("committed_hours", 0)
    if wo["estimated_hours"] > remaining:
        raise err_outage_capacity_exceeded()

    # Execute
    wo["outage_window_id"] = outage_window_id
    wo["status"] = "SCHEDULED"
    db.touch(wo)

    window["committed_hours"] = window.get("committed_hours", 0) + wo["estimated_hours"]
    db.touch(window)

    return success_object(work_order_view(wo))


@bp.post("/work-orders/<id>/start")
def start_work_order(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    wo = get_work_order(id)

    if wo["status"] != "SCHEDULED":
        raise err_state_transition("Work order is not SCHEDULED")

    # Segregation of duties: only the assignee
    if actor.user_id != wo["assigned_technician_id"]:
        raise err_segregation_of_duties("Only the assigned technician may start")

    # Window must be SWITCHING or CLEARED
    window = db.outage_windows.get(wo.get("outage_window_id"))
    if window is None or window["status"] not in ("SWITCHING", "CLEARED"):
        raise err_state_transition("Linked window is not SWITCHING or CLEARED")

    wo["status"] = "IN_PROGRESS"
    db.touch(wo)
    return success_object(work_order_view(wo))


@bp.post("/work-orders/<id>/complete")
def complete_work_order(id):
    actor = get_actor()
    require_roles(actor, ["Technician"])
    wo = get_work_order(id)
    payload = body()

    if wo["status"] != "IN_PROGRESS":
        raise err_state_transition("Work order is not IN_PROGRESS")

    # Segregation of duties: only the assignee
    if actor.user_id != wo["assigned_technician_id"]:
        raise err_segregation_of_duties("Only the assigned technician may complete")

    labor_lines = payload.get("labor_lines", [])
    parts_lines = payload.get("parts_lines", [])

    # Validate labor lines
    if not isinstance(labor_lines, list):
        raise err_validation("labor_lines must be an array")
    for line in labor_lines:
        if not isinstance(line, dict):
            raise err_validation("labor line must be an object")
        if "hours" not in line or "rate_per_hour" not in line:
            raise err_validation("labor line requires hours and rate_per_hour")

    # Validate parts lines
    if not isinstance(parts_lines, list):
        raise err_validation("parts_lines must be an array")
    for line in parts_lines:
        if not isinstance(line, dict):
            raise err_validation("parts line must be an object")
        if "quantity" not in line or "unit_price" not in line:
            raise err_validation("parts line requires quantity and unit_price")

    wo["labor_lines"] = labor_lines
    wo["parts_lines"] = parts_lines

    # Compute cost rollup
    cost_subtotal, mobilization_fee, total_cost = compute_cost_rollup(labor_lines, parts_lines)
    wo["cost_subtotal"] = cost_subtotal
    wo["mobilization_fee"] = mobilization_fee
    wo["total_cost"] = total_cost
    wo["completed_at"] = db.now_iso()
    wo["status"] = "COMPLETED"
    db.touch(wo)

    # Cascade: Defect WORK_ORDERED -> RESOLVED
    defect = db.defects.get(wo["defect_id"])
    if defect and defect["status"] == "WORK_ORDERED":
        defect["status"] = "RESOLVED"
        db.touch(defect)
        # Recompute condition score (defect penalty removed for RESOLVED)
        refresh_asset_condition_and_due(wo["asset_id"])

    return success_object(work_order_view(wo))


@bp.post("/work-orders/<id>/verify")
def verify_work_order(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    wo = get_work_order(id)

    if wo["status"] != "COMPLETED":
        raise err_state_transition("Work order is not COMPLETED")

    wo["status"] = "VERIFIED"
    db.touch(wo)

    # Cascade: Defect RESOLVED -> VERIFIED
    defect = db.defects.get(wo["defect_id"])
    if defect and defect["status"] == "RESOLVED":
        defect["status"] = "VERIFIED"
        db.touch(defect)

    # Asset: refresh last_maintenance_completed_at and recompute next_due_date
    asset = db.assets.get(wo["asset_id"])
    if asset:
        asset["last_maintenance_completed_at"] = db.now_iso()
        refresh_asset_condition_and_due(wo["asset_id"])

    return success_object(work_order_view(wo))


@bp.post("/work-orders/<id>/cancel")
def cancel_work_order(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    wo = get_work_order(id)

    if wo["status"] not in ("DRAFT", "SCHEDULED"):
        raise err_state_transition("Work order is not DRAFT or SCHEDULED")

    was_scheduled = wo["status"] == "SCHEDULED"
    old_window_id = wo.get("outage_window_id")

    wo["status"] = "CANCELLED"
    db.touch(wo)

    if was_scheduled and old_window_id:
        # Compensate window hours
        window = db.outage_windows.get(old_window_id)
        if window:
            window["committed_hours"] = window.get("committed_hours", 0) - wo["estimated_hours"]
            db.touch(window)

    # Defect WORK_ORDERED -> OPEN
    defect = db.defects.get(wo["defect_id"])
    if defect and defect["status"] == "WORK_ORDERED":
        defect["status"] = "OPEN"
        db.touch(defect)

    return success_object(work_order_view(wo))
