"""Work orders, the change-order cycle, and labor entries (PRD 3.5, 3.6)."""

from flask import Blueprint, request

import clock
import db
import response
from errors import (
    not_found, validation, invalid_state, already_terminal, ApiError,
    ERR_OPEN_COMPLIANCE_HOLD, ERR_WINTERIZATION_WINDOW,
    ERR_SUBCONTRACTOR_NOT_ALLOWED,
)
from middleware import require_roles, check_owner_work_order, check_owner_job
from money import dec, rhu, SUBCONTRACTOR_MARKUP, NO_MARKUP
from services import lifecycle, storage as storage_svc
from validation import (
    get_body, req_str, req_enum, req_number, req_int, parse_pagination, page,
)
from .jobs import get_job_or_404

bp = Blueprint("work_orders", __name__)

WO_TYPES = (
    "BOTTOM_PAINT", "MECHANICAL", "ELECTRICAL", "RIGGING", "FIBERGLASS",
    "WINTERIZATION", "SHRINK_WRAP",
)
SEASONAL_TYPES = ("WINTERIZATION", "SHRINK_WRAP")
# Job states in which a work order may be created.
CREATABLE_JOB_STATES = ("DRAFT", "INTAKE", "HAUL_SCHEDULED", "ON_HARD", "WORK_IN_PROGRESS")
WORKER_TYPES = ("YARD_CREW", "SUBCONTRACTOR")


def get_wo_or_404(wo_id):
    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise not_found(f"WorkOrder '{wo_id}' does not exist")
    return wo


def _compute_quoted_total(quoted_hours, quoted_rate_cents, quoted_parts_cents):
    """round_half_up(quoted_hours x quoted_rate_cents) + quoted_parts_cents --
    rounding pinned to the labor product only."""
    return rhu(dec(quoted_hours) * dec(quoted_rate_cents)) + quoted_parts_cents


def _in_winterization_window(d):
    """Current month-day within [09-15, 12-15] inclusive."""
    return (d.month, d.day) >= (9, 15) and (d.month, d.day) <= (12, 15)


def _assert_wo_not_terminal(wo):
    if wo["status"] == "CANCELLED":
        raise already_terminal("WorkOrder is CANCELLED")


@bp.post("/yard/work-orders")
@require_roles("ServiceWriter")
def create_work_order():
    body = get_body()
    job_id = req_str(body, "job_id")
    job = get_job_or_404(job_id)
    wo_type = req_enum(body, "type", WO_TYPES)
    description = req_str(body, "description")
    quoted_hours = req_number(body, "quoted_hours", ge=0)
    quoted_rate = req_int(body, "quoted_rate_cents", ge=0)
    quoted_parts = req_int(body, "quoted_parts_cents", ge=0)

    if job["status"] not in CREATABLE_JOB_STATES:
        raise invalid_state(
            f"Work orders cannot be created while the job is {job['status']}")
    if wo_type in SEASONAL_TYPES and not _in_winterization_window(clock.today()):
        raise ApiError(ERR_WINTERIZATION_WINDOW, 422,
                       "WINTERIZATION / SHRINK_WRAP work is gated to Sep 15 - Dec 15")

    now = db.now_iso()
    wo = {
        "id": db.new_id(),
        "job_id": job["id"],
        "type": wo_type,
        "description": description,
        "quoted_hours": quoted_hours,
        "quoted_rate_cents": quoted_rate,
        "quoted_parts_cents": quoted_parts,
        "quoted_total_cents": _compute_quoted_total(quoted_hours, quoted_rate, quoted_parts),
        "actual_cost_cents": 0,
        "revision": 0,
        "change_note": None,
        "status": "ESTIMATE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.work_orders[wo["id"]] = wo
    return response.success_object(db.pub(wo), status=201)


@bp.get("/yard/work-orders/<workOrderId>")
@require_roles("ServiceWriter", "YardManager", "Owner")
def get_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    check_owner_work_order(wo)
    return response.success_object(db.pub(wo))


@bp.get("/yard/refit-jobs/<jobId>/work-orders")
@require_roles("ServiceWriter", "YardManager", "Owner")
def list_work_orders(jobId):
    job = get_job_or_404(jobId)
    check_owner_job(job)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [w for w in db.work_orders.values() if w["job_id"] == job["id"]]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)


@bp.post("/yard/work-orders/<workOrderId>/approve")
@require_roles("Owner")
def approve_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    # Ownership scope (gate 3): acting owner must own the vessel.
    check_owner_work_order(wo)
    _assert_wo_not_terminal(wo)
    if wo["status"] != "ESTIMATE":
        raise invalid_state("Only an ESTIMATE work order can be approved")
    wo["status"] = "APPROVED"
    db.touch(wo)
    return response.success_object(db.pub(wo))


@bp.post("/yard/work-orders/<workOrderId>/start")
@require_roles("ServiceWriter")
def start_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    _assert_wo_not_terminal(wo)
    if wo["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED work order can be started")
    job = db.jobs.get(wo["job_id"])
    if job is None or job["status"] not in ("ON_HARD", "WORK_IN_PROGRESS"):
        raise invalid_state("The vessel must be on the hard to start work")
    if job["open_hold_count"] > 0:
        raise ApiError(ERR_OPEN_COMPLIANCE_HOLD, 409,
                       "Work order start is blocked by an open compliance hold")
    wo["status"] = "IN_PROGRESS"
    db.touch(wo)
    if job["status"] == "ON_HARD":
        job["status"] = "WORK_IN_PROGRESS"
        db.touch(job)
    return response.success_object(db.pub(wo))


@bp.post("/yard/work-orders/<workOrderId>/request-change")
@require_roles("Owner", "ServiceWriter")
def request_change(workOrderId):
    wo = get_wo_or_404(workOrderId)
    check_owner_work_order(wo)
    body = get_body()
    note = req_str(body, "change_note")
    _assert_wo_not_terminal(wo)
    if wo["status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS work order can be change-requested")
    wo["status"] = "CHANGE_REQUESTED"
    wo["change_note"] = note
    db.touch(wo)
    return response.success_object(db.pub(wo))


@bp.post("/yard/work-orders/<workOrderId>/requote")
@require_roles("ServiceWriter")
def requote_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    body = get_body()
    quoted_hours = req_number(body, "quoted_hours", ge=0)
    quoted_rate = req_int(body, "quoted_rate_cents", ge=0)
    quoted_parts = req_int(body, "quoted_parts_cents", ge=0)
    _assert_wo_not_terminal(wo)
    if wo["status"] != "CHANGE_REQUESTED":
        raise invalid_state("Only a CHANGE_REQUESTED work order can be re-quoted")
    wo["quoted_hours"] = quoted_hours
    wo["quoted_rate_cents"] = quoted_rate
    wo["quoted_parts_cents"] = quoted_parts
    wo["quoted_total_cents"] = _compute_quoted_total(quoted_hours, quoted_rate, quoted_parts)
    wo["revision"] += 1
    wo["status"] = "ESTIMATE"
    db.touch(wo)
    return response.success_object(db.pub(wo))


@bp.post("/yard/work-orders/<workOrderId>/complete")
@require_roles("ServiceWriter")
def complete_work_order(workOrderId):
    wo = get_wo_or_404(workOrderId)
    _assert_wo_not_terminal(wo)
    if wo["status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS work order can be completed")
    wo["status"] = "COMPLETE"
    db.touch(wo)
    if wo["actual_cost_cents"] > 0:
        storage_svc.post_ledger(
            wo["job_id"], "CHARGE", "LABOR", wo["actual_cost_cents"],
            memo=f"Labor for work order {wo['id']}",
            source_work_order_id=wo["id"],
        )
    job = db.jobs.get(wo["job_id"])
    if job is not None:
        before = job["status"]
        lifecycle.reevaluate_readiness(job)
        if job["status"] != before:
            db.touch(job)
    return response.success_object(db.pub(wo))


@bp.post("/yard/labor-entries")
@require_roles("ServiceWriter")
def create_labor_entry():
    body = get_body()
    wo_id = req_str(body, "work_order_id")
    wo = get_wo_or_404(wo_id)
    worker_type = req_enum(body, "worker_type", WORKER_TYPES)
    hours = req_number(body, "hours", gt=0)
    rate_cents = req_int(body, "rate_cents", gt=0)
    sub_name = body.get("subcontractor_name")
    if worker_type == "SUBCONTRACTOR":
        if not isinstance(sub_name, str):
            raise validation("Field 'subcontractor_name' is required for SUBCONTRACTOR labor")
    elif sub_name is not None and not isinstance(sub_name, str):
        raise validation("Field 'subcontractor_name' must be a string")

    if wo["status"] != "IN_PROGRESS":
        raise invalid_state("Labor may be logged only on an IN_PROGRESS work order")
    if worker_type == "SUBCONTRACTOR" and wo["type"] == "BOTTOM_PAINT":
        raise ApiError(ERR_SUBCONTRACTOR_NOT_ALLOWED, 422,
                       "Subcontractor labor is prohibited on BOTTOM_PAINT work orders")

    markup = SUBCONTRACTOR_MARKUP if worker_type == "SUBCONTRACTOR" else NO_MARKUP
    line_cost = rhu(dec(hours) * dec(rate_cents) * markup)
    entry = {
        "id": db.new_id(),
        "work_order_id": wo["id"],
        "worker_type": worker_type,
        "hours": hours,
        "rate_cents": rate_cents,
        "subcontractor_name": sub_name,
        "line_cost_cents": line_cost,
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    db.labor_entries[entry["id"]] = entry
    # Per-line rounding pinned: round each line first, then sum.
    wo["actual_cost_cents"] = sum(
        e["line_cost_cents"] for e in db.labor_entries.values()
        if e["work_order_id"] == wo["id"]
    )
    db.touch(wo)
    return response.success_object(db.pub(entry), status=201)


@bp.get("/yard/work-orders/<workOrderId>/labor-entries")
@require_roles("ServiceWriter", "YardManager", "Accountant")
def list_labor_entries(workOrderId):
    wo = get_wo_or_404(workOrderId)
    limit, offset = parse_pagination()
    items = [e for e in db.labor_entries.values() if e["work_order_id"] == wo["id"]]
    items, total = page(items, limit, offset)
    return response.success_list(items, limit, offset, total)
