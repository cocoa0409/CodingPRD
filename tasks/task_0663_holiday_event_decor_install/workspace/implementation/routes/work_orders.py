"""WorkOrder endpoints: create/read, schedule/dispatch/complete/cancel, billing."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_str, require_enum,
                        require_datetime, parse_pagination, paginate, parse_iso)
from services.calculations import (compute_route_minutes,
                                    compute_crew_utilization_planned,
                                    compute_crew_utilization_actual)

bp = Blueprint("work_orders", __name__)

JOB_TYPES = {"INSTALL", "REFRESH", "TAKEDOWN"}
BUFFER = timedelta(days=1)


def _get_wo_or_404(wo_id):
    rec = db.work_orders.get(wo_id)
    if rec is None:
        raise errors.not_found("Work order not found")
    return rec


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------
@bp.post("/work-orders")
def create_work_order():
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    body = get_json_body()
    contract_id = require_str(body, "contract_id")
    job_type = require_enum(body, "job_type", JOB_TYPES)
    if contract_id not in db.contracts:
        raise errors.reference_not_found("contract_id does not exist")

    rec = base_fields()
    rec.update({
        "contract_id": contract_id,
        "crew_id": None,
        "job_type": job_type,
        "scheduled_date": None,
        "route_total_minutes": None,
        "schedule_status": "UNSCHEDULED",
        "billing_status": "PENDING",
    })
    db.work_orders[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/work-orders/<id>")
def get_work_order(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    rec = _get_wo_or_404(id)
    return success(public(rec))


@bp.get("/work-orders")
def list_work_orders():
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    limit, offset = parse_pagination()
    contract_id = request.args.get("contract_id")
    crew_id = request.args.get("crew_id")
    schedule_status = request.args.get("schedule_status")
    records = list(db.work_orders.values())
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if crew_id is not None:
        records = [r for r in records if r.get("crew_id") == crew_id]
    if schedule_status is not None:
        records = [r for r in records if r["schedule_status"] == schedule_status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
def _crew_double_booked(crew_id, requested_dt, exclude_wo_id):
    """Closed-interval buffer-strict check: a date within 1 day of an existing
    non-cancelled window on this crew is a collision."""
    for wo in db.work_orders.values():
        if wo["id"] == exclude_wo_id:
            continue
        if wo.get("crew_id") != crew_id:
            continue
        if wo["schedule_status"] == "CANCELLED":
            continue
        existing = wo.get("scheduled_date")
        if existing is None:
            continue
        existing_dt = parse_iso(existing)
        if existing_dt is None:
            continue
        # collision if the gap is within the one-day buffer (closed-interval,
        # buffer-strict): a date falling within one day — inclusive of exactly
        # one day — of an existing window is a collision (PRD §3.4).
        if abs(requested_dt - existing_dt) <= BUFFER:
            return True
    return False


@bp.post("/work-orders/<id>/schedule")
def schedule_work_order(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    wo = _get_wo_or_404(id)
    body = get_json_body()
    crew_id = require_str(body, "crew_id")
    scheduled_date = require_datetime(body, "scheduled_date")
    # body FK existence (priority 5)
    if crew_id not in db.crews:
        raise errors.reference_not_found("crew_id does not exist")

    # state-machine guard (priority 8)
    if wo["schedule_status"] != "UNSCHEDULED":
        raise errors.invalid_state()

    # business: crew double-booking (priority 12) before contract-not-active (14)
    requested_dt = parse_iso(scheduled_date)
    if _crew_double_booked(crew_id, requested_dt, id):
        raise errors.crew_double_booked()

    # business: contract must be ACTIVE (priority 14)
    contract = db.contracts.get(wo["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise errors.contract_not_active()

    # at least one visit
    visits = [v for v in db.visits.values() if v["work_order_id"] == id]
    if not visits:
        raise errors.invalid_state("Work order has no visits")

    wo["crew_id"] = crew_id
    wo["scheduled_date"] = scheduled_date
    wo["route_total_minutes"] = compute_route_minutes(wo)
    wo["schedule_status"] = "SCHEDULED"
    touch(wo)

    crew = db.crews[crew_id]
    crew["planned_utilization_pct"] = compute_crew_utilization_planned(crew)
    touch(crew)
    return success(public(wo))


@bp.post("/work-orders/<id>/dispatch")
def dispatch_work_order(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    wo = _get_wo_or_404(id)
    if wo["schedule_status"] != "SCHEDULED":
        raise errors.invalid_state()
    wo["schedule_status"] = "DISPATCHED"
    touch(wo)
    return success(public(wo))


@bp.post("/work-orders/<id>/complete")
def complete_work_order(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    wo = _get_wo_or_404(id)
    if wo["schedule_status"] != "DISPATCHED":
        raise errors.invalid_state()
    # every visit must be COMPLETED or SKIPPED
    visits = [v for v in db.visits.values() if v["work_order_id"] == id]
    if any(v["visit_status"] == "PLANNED" for v in visits):
        raise errors.visits_not_complete()

    wo["schedule_status"] = "COMPLETED"
    touch(wo)

    crew_id = wo.get("crew_id")
    if crew_id and crew_id in db.crews:
        crew = db.crews[crew_id]
        crew["actual_utilization_pct"] = compute_crew_utilization_actual(crew)
        touch(crew)
    return success(public(wo))


@bp.post("/work-orders/<id>/cancel")
def cancel_work_order(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    wo = _get_wo_or_404(id)
    if wo["schedule_status"] not in ("UNSCHEDULED", "SCHEDULED"):
        raise errors.invalid_state()
    was_scheduled = wo["schedule_status"] == "SCHEDULED"
    crew_id = wo.get("crew_id")
    wo["schedule_status"] = "CANCELLED"
    touch(wo)
    # if it was SCHEDULED, free crew window + recompute planned utilization
    if was_scheduled and crew_id and crew_id in db.crews:
        crew = db.crews[crew_id]
        crew["planned_utilization_pct"] = compute_crew_utilization_planned(crew)
        touch(crew)
    return success(public(wo))


# ---------------------------------------------------------------------------
# Billing dimension
# ---------------------------------------------------------------------------
@bp.post("/work-orders/<id>/invoice")
def invoice_work_order(id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    wo = _get_wo_or_404(id)
    if wo["billing_status"] != "PENDING":
        raise errors.invalid_state()
    if wo["schedule_status"] != "COMPLETED":
        raise errors.workorder_not_completed()
    wo["billing_status"] = "INVOICED"
    touch(wo)
    return success(public(wo))


@bp.post("/work-orders/<id>/mark-paid")
def mark_paid_work_order(id):
    _, role = get_identity()
    require_role(role, ["AccountManager"])
    wo = _get_wo_or_404(id)
    if wo["billing_status"] != "INVOICED":
        raise errors.invalid_state()
    wo["billing_status"] = "PAID"
    touch(wo)
    return success(public(wo))
