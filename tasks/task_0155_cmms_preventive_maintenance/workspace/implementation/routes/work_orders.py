"""WorkOrder routes (PRD §3.4–§3.7, §4).

Covers corrective create, fetch, list (reverse filters), the full execution
state machine (release/assign/schedule-window/unassign/start/hold/resume/
close/cancel), and the parts commit action. Reservation create/list live in
reservations.py.
"""
from flask import Blueprint, request

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import (require_str, require_enum, require_number, require_int,
                     require_dt, parse_pagination, paginate)
from response import object_response, array_response
from services import calc, workflow

bp = Blueprint("work_orders", __name__)

WO_TYPES = {"PREVENTIVE", "CORRECTIVE"}
SEVERITIES = {"ROUTINE", "MAJOR", "OVERHAUL"}
RESERVABLE_STATES = {"UNASSIGNED", "ASSIGNED", "IN_PROGRESS", "ON_HOLD"}
PLANNER_ROLES = ["Planner", "MaintenanceManager"]


# ---------------------------------------------------------------------------
# Create (corrective only) — PRD §3.4. Preventive WOs are never created here.
# ---------------------------------------------------------------------------
@bp.post("/work-orders")
def create_work_order():
    _, role = authenticate()
    authorize(role, PLANNER_ROLES)
    body = get_json_body()
    asset_id = require_str(body, "asset_id")
    wo_type = require_enum(body, "wo_type", WO_TYPES)
    severity = require_enum(body, "severity", SEVERITIES)
    est = require_number(body, "estimated_labor_hours", gt=0)
    if wo_type != "CORRECTIVE":
        # PRD §3.4: only corrective work orders are created directly.
        raise errors.invalid_request("Only CORRECTIVE work orders may be created directly.")
    with db.LOCK:
        asset = db.assets.get(asset_id)
        if asset is None:
            raise errors.reference_not_found("asset_id does not reference an existing asset.")
        wo = workflow.build_work_order(asset, "CORRECTIVE", severity, est, pm_schedule=None)
        return object_response(serialize.work_order(wo), 201)


@bp.get("/work-orders/<wid>")
def get_work_order(wid):
    _, role = authenticate()
    authorize(role, ["Planner", "MaintenanceManager", "Technician", "WarrantyAdmin", "InventoryClerk"])
    with db.LOCK:
        rec = db.work_orders.get(wid)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.work_order(rec), 200)


@bp.get("/work-orders")
def list_work_orders():
    _, role = authenticate()
    authorize(role, ["Planner", "MaintenanceManager", "Technician", "WarrantyAdmin", "InventoryClerk"])
    limit, offset = parse_pagination()
    asset_id = request.args.get("asset_id")
    pm_schedule_id = request.args.get("pm_schedule_id")
    assigned_technician_id = request.args.get("assigned_technician_id")
    warranty_claim_id = request.args.get("warranty_claim_id")
    with db.LOCK:
        items = sorted(db.work_orders.values(), key=lambda r: r["_seq"])
        if asset_id is not None:
            items = [w for w in items if w["asset_id"] == asset_id]
        if pm_schedule_id is not None:
            items = [w for w in items if w["pm_schedule_id"] == pm_schedule_id]
        if assigned_technician_id is not None:
            items = [w for w in items if w["assigned_technician_id"] == assigned_technician_id]
        if warranty_claim_id is not None:
            items = [w for w in items if w["warranty_claim_id"] == warranty_claim_id]
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.work_order(w) for w in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Planning lifecycle (Planner / MaintenanceManager).
# ---------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/release-to-queue")
def release_to_queue(wid):
    _, role = authenticate()
    authorize(role, PLANNER_ROLES)
    with db.LOCK:
        wo = _get_wo(wid)
        if wo["execution_status"] != "DRAFT":
            raise errors.invalid_state("Work order is not in DRAFT.")
        asset = db.assets.get(wo["asset_id"])
        if asset is not None and asset["status"] == "RETIRED":
            raise errors.invalid_state("Asset is RETIRED.")
        wo["execution_status"] = "UNASSIGNED"
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/assign")
def assign(wid):
    _, role = authenticate()
    authorize(role, PLANNER_ROLES)
    body = get_json_body()
    with db.LOCK:
        wo = _get_wo(wid)
        technician_id = require_str(body, "technician_id")
        tech = db.technicians.get(technician_id)
        if tech is None:
            raise errors.reference_not_found("technician_id does not reference an existing technician.")
        if wo["execution_status"] != "UNASSIGNED":
            raise errors.invalid_state("Work order is not UNASSIGNED.")
        # Skill gate (priority 8).
        if not calc.skill_eligible(tech, wo):
            raise errors.ApiError(errors.ERR_SKILL_INSUFFICIENT,
                                  "Technician skill rank is below the work order's severity rank.", 422)
        # Backlog gate (priority 14).
        if tech["backlog_hours"] + wo["estimated_labor_hours"] > tech["weekly_capacity_hours"]:
            raise errors.ApiError(errors.ERR_BACKLOG_EXCEEDED,
                                  "Assigning would exceed the technician's weekly capacity.", 422)
        wo["execution_status"] = "ASSIGNED"
        wo["assigned_technician_id"] = tech["id"]
        db.touch(wo)
        calc.recompute_backlog(tech)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/schedule-window")
def schedule_window(wid):
    _, role = authenticate()
    authorize(role, PLANNER_ROLES)
    body = get_json_body()
    with db.LOCK:
        wo = _get_wo(wid)
        start = require_dt(body, "scheduled_start")
        end = require_dt(body, "scheduled_end")
        if wo["execution_status"] != "ASSIGNED":
            raise errors.invalid_state("Work order must be ASSIGNED to book a window.")
        if not (end > start):
            raise errors.invalid_request("scheduled_end must be strictly after scheduled_start.")
        # Double-booking (priority 20): half-open [start, end); touching is OK.
        tech_id = wo["assigned_technician_id"]
        for other in db.work_orders.values():
            if other["id"] == wid:
                continue
            if other["assigned_technician_id"] != tech_id:
                continue
            if other["execution_status"] in ("CLOSED", "CANCELLED"):
                continue
            os, oe = other.get("scheduled_start"), other.get("scheduled_end")
            if os is None or oe is None:
                continue
            os_dt = db.parse_stored_dt(os)
            oe_dt = db.parse_stored_dt(oe)
            # positive-length intersection: start < oe AND os < end
            if start < oe_dt and os_dt < end:
                raise errors.ApiError(errors.ERR_TECH_DOUBLE_BOOKED,
                                      "Window overlaps another booked window for this technician.", 409)
        wo["scheduled_start"] = db.iso(start)
        wo["scheduled_end"] = db.iso(end)
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/unassign")
def unassign(wid):
    _, role = authenticate()
    authorize(role, PLANNER_ROLES)
    with db.LOCK:
        wo = _get_wo(wid)
        if wo["execution_status"] != "ASSIGNED":
            raise errors.invalid_state("Work order is not ASSIGNED.")
        tech = db.technicians.get(wo["assigned_technician_id"])
        wo["execution_status"] = "UNASSIGNED"
        wo["assigned_technician_id"] = None
        db.touch(wo)
        if tech is not None:
            calc.recompute_backlog(tech)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/cancel")
def cancel(wid):
    _, role = authenticate()
    authorize(role, PLANNER_ROLES)
    with db.LOCK:
        wo = _get_wo(wid)
        if wo["execution_status"] not in ("DRAFT", "UNASSIGNED", "ASSIGNED"):
            raise errors.invalid_state("Work order cannot be cancelled from its current state.")
        workflow.cancel_cascade(wo)
        wo["execution_status"] = "CANCELLED"
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


# ---------------------------------------------------------------------------
# Execution lifecycle (Technician, assigned-owner only).
# ---------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/start")
def start(wid):
    user_id, role = authenticate()
    authorize(role, ["Technician"])
    with db.LOCK:
        wo = _get_wo(wid)
        _require_owner(wo, user_id)
        if wo["execution_status"] != "ASSIGNED":
            raise errors.invalid_state("Work order is not ASSIGNED.")
        if wo["parts_status"] not in ("NONE", "RESERVED"):
            raise errors.invalid_state("Work order parts must be NONE or RESERVED to start.")
        if wo["opened_at"] is None:
            wo["opened_at"] = db.logical_now_iso()
        wo["execution_status"] = "IN_PROGRESS"
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/hold")
def hold(wid):
    user_id, role = authenticate()
    authorize(role, ["Technician"])
    with db.LOCK:
        wo = _get_wo(wid)
        _require_owner(wo, user_id)
        if wo["execution_status"] != "IN_PROGRESS":
            raise errors.invalid_state("Work order is not IN_PROGRESS.")
        wo["execution_status"] = "ON_HOLD"
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/resume")
def resume(wid):
    user_id, role = authenticate()
    authorize(role, ["Technician"])
    with db.LOCK:
        wo = _get_wo(wid)
        _require_owner(wo, user_id)
        if wo["execution_status"] != "ON_HOLD":
            raise errors.invalid_state("Work order is not ON_HOLD.")
        wo["execution_status"] = "IN_PROGRESS"
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/close")
def close(wid):
    user_id, role = authenticate()
    authorize(role, ["Technician"])
    body = get_json_body()
    with db.LOCK:
        wo = _get_wo(wid)
        _require_owner(wo, user_id)
        actual_cost = require_int(body, "actual_cost_cents", minimum=0)
        if wo["execution_status"] != "IN_PROGRESS":
            raise errors.invalid_state("Work order is not IN_PROGRESS.")
        # parts-committed guard (priority 16): no RESERVED reservation remains.
        for r in db.part_reservations.values():
            if r["work_order_id"] == wid and r["status"] == "RESERVED":
                raise errors.ApiError(errors.ERR_PARTS_NOT_COMMITTED,
                                      "A reservation on this work order is still RESERVED.", 409)
        # downtime-open guard (priority 17): no OPEN downtime references this WO.
        for d in db.downtime_events.values():
            if d.get("work_order_id") == wid and d["status"] == "OPEN":
                raise errors.ApiError(errors.ERR_DOWNTIME_OPEN,
                                      "An open downtime event references this work order.", 409)
        wo["actual_cost_cents"] = actual_cost
        wo["closed_at"] = db.logical_now_iso()
        wo["execution_status"] = "CLOSED"
        db.touch(wo)
        tech = db.technicians.get(wo["assigned_technician_id"])
        if tech is not None:
            calc.recompute_backlog(tech)
        workflow.close_cascade(wo)
        return object_response(serialize.work_order(wo), 200)


@bp.post("/work-orders/<wid>/commit-parts")
def commit_parts(wid):
    _, role = authenticate()
    authorize(role, ["InventoryClerk"])
    with db.LOCK:
        wo = _get_wo(wid)
        if wo["execution_status"] != "IN_PROGRESS":
            raise errors.invalid_state("Work order must be IN_PROGRESS to commit parts.")
        reserved = [r for r in db.part_reservations.values()
                    if r["work_order_id"] == wid and r["status"] == "RESERVED"]
        if not reserved:
            raise errors.invalid_state("No RESERVED reservation to commit.")
        affected_parts = set()
        for r in reserved:
            part = db.spare_parts[r["spare_part_id"]]
            r["status"] = "COMMITTED"
            r["committed_cost_cents"] = r["qty"] * part["unit_cost_cents"]
            db.touch(r)
            affected_parts.add(part["id"])
        # reserved_qty unchanged in value (COMMITTED still counts) but each part
        # is reconciled to keep version/updated_at consistent (PRD §2.4/§3.7).
        for pid in affected_parts:
            calc.recompute_reserved_qty(db.spare_parts[pid])
        wo["parts_status"] = "COMMITTED"
        db.touch(wo)
        return object_response(serialize.work_order(wo), 200)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _get_wo(wid):
    wo = db.work_orders.get(wid)
    if wo is None:
        raise errors.not_found()
    return wo


def _require_owner(wo, user_id):
    """Execution actions are reserved to the assigned technician (PRD §3.6):
    the acting X-User-ID (the Technician.id) must equal assigned_technician_id.
    Treated as an authorization/ownership concern -> ERR_FORBIDDEN."""
    if wo["assigned_technician_id"] != user_id:
        raise errors.forbidden("Only the assigned technician may execute this work order.")
