"""WorkOrder + WorkOrderLineItem endpoints."""
from flask import Blueprint, request

import db
from db import _parse_iso, _format_iso
from middleware import get_actor, require_roles, technician_capability_check
from response import success_object, success_list
from errors import (
    err_invalid_request, err_invalid_state, err_not_found, err_conflict,
    err_stale_version, err_unauthorized,
)
from services.common import (
    body, require_string, require_int, require_number,
    parse_pagination, paginate, get_plan, get_work_order, sweep_notice_expiry,
    compute_mobilization_tier, recompute_plan_provisional, recompute_plan_final,
    compute_line_cents,
)

bp = Blueprint("work_orders", __name__)

READ_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead"]


def wo_view(w):
    return {
        "id": w["id"],
        "plan_id": w["plan_id"],
        "crew_lead_id": w["crew_lead_id"],
        "execution_status": w["execution_status"],
        "billing_status": w["billing_status"],
        "mobilization_tier": w["mobilization_tier"],
        "completed_at": w["completed_at"],
        "warranty_expires_at": w["warranty_expires_at"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def li_view(li):
    return {
        "id": li["id"],
        "work_order_id": li["work_order_id"],
        "pay_item_code": li["pay_item_code"],
        "scheduled_qty": li["scheduled_qty"],
        "installed_qty": li["installed_qty"],
        "unit_price_cents": li["unit_price_cents"],
        "provisional_line_cents": li["provisional_line_cents"],
        "final_line_cents": li["final_line_cents"],
        "created_at": li["created_at"],
        "updated_at": li["updated_at"],
        "version": li["version"],
    }


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------

@bp.post("/sewer/rehab-plans/<id>/work-orders")
def create_work_order(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    plan = get_plan(id)
    payload = body()
    crew_lead_id = require_string(payload, "crew_lead_id")
    crew = db.technicians.get(crew_lead_id)
    if crew is None:
        raise err_not_found("crew lead technician not found")
    # plan must be APPROVED (per endpoint description: issue under APPROVED plan)
    if plan["status"] != "APPROVED":
        raise err_conflict("ERR_PLAN_NOT_APPROVED", "work order must be issued under an APPROVED plan")
    if not crew.get("active", True):
        raise err_conflict("ERR_NOT_ASSIGNED_CREW", "crew lead is inactive")
    if "CREW_LEAD" not in (crew.get("capabilities") or []):
        raise err_conflict("ERR_NOT_ASSIGNED_CREW", "technician lacks CREW_LEAD capability")
    segment = db.segments[plan["segment_id"]]
    tier = compute_mobilization_tier(segment)
    ent = {
        "id": db.new_id(),
        "plan_id": plan["id"],
        "crew_lead_id": crew_lead_id,
        "execution_status": "ISSUED",
        "billing_status": "UNBILLED",
        "mobilization_tier": tier,
        "completed_at": None,
        "warranty_expires_at": None,
    }
    db.stamp_new(ent)
    db.work_orders[ent["id"]] = ent
    # adding a work order affects provisional total via mobilization fee
    recompute_plan_provisional(plan["id"])
    sweep_notice_expiry()
    return success_object(wo_view(ent), status=201)


@bp.get("/sewer/work-orders/<id>")
def get_work_order_route(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    w = get_work_order(id)
    return success_object(wo_view(w))


@bp.get("/sewer/rehab-plans/<id>/work-orders")
def list_plan_work_orders(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    plan = get_plan(id)
    limit, offset = parse_pagination()
    items = [w for w in db.work_orders.values() if w["plan_id"] == plan["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([wo_view(w) for w in page], limit, offset, total)


@bp.get("/sewer/work-orders")
def list_work_orders_xplan():
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer", "CrewLead"])
    limit, offset = parse_pagination()
    items = list(db.work_orders.values())
    cl = request.args.get("crew_lead_id")
    if cl:
        items = [w for w in items if w["crew_lead_id"] == cl]
    es = request.args.get("execution_status")
    if es:
        items = [w for w in items if w["execution_status"] == es]
    page, total = paginate(items, limit, offset)
    return success_list([wo_view(w) for w in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Crew gate
# ---------------------------------------------------------------------------

def _crew_gate(actor, wo):
    tech = technician_capability_check(actor, "CREW_LEAD")
    if tech["id"] != wo["crew_lead_id"]:
        raise err_conflict("ERR_NOT_ASSIGNED_CREW", "acting CrewLead is not the assigned crew lead")
    if not tech.get("active", True):
        raise err_unauthorized("technician inactive")
    return tech


def _earliest_event_start(wo_id):
    """Earliest bypass or excavation start among notices on this work order.

    The mobilize rule applies to notices whose event_start <= earliest bypass/excavation start.
    For simplicity we use the minimum event_start over all notices on the work order.
    """
    evs = [db._parse_iso(n["event_start"]) for n in db.notices.values() if n["work_order_id"] == wo_id]
    return min(evs) if evs else None


# ---------------------------------------------------------------------------
# Execution transitions
# ---------------------------------------------------------------------------

@bp.post("/sewer/work-orders/<id>/mobilize")
def mobilize(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    if wo["execution_status"] != "ISSUED":
        raise err_invalid_state("work order not ISSUED")
    _crew_gate(actor, wo)
    plan = db.plans[wo["plan_id"]]
    if plan["status"] not in ("APPROVED", "EXECUTING"):
        raise err_conflict("ERR_PLAN_NOT_APPROVED", "parent plan not APPROVED/EXECUTING")
    segment = db.segments[plan["segment_id"]]
    if plan["method"] == "FULL_REPLACE":
        has_approved_bypass = any(
            b["work_order_id"] == wo["id"] and b["status"] in ("APPROVED", "ACTIVE")
            for b in db.bypass_plans.values()
        )
        if not has_approved_bypass:
            raise err_conflict("ERR_BYPASS_REQUIRED", "FULL_REPLACE requires an APPROVED BypassPlan")
    # notice gate
    earliest = _earliest_event_start(wo["id"])
    if earliest is not None:
        for n in db.notices.values():
            if n["work_order_id"] != wo["id"]:
                continue
            ev = _parse_iso(n["event_start"])
            if ev <= earliest and n["status"] not in ("SENT", "ACKNOWLEDGED"):
                raise err_conflict("ERR_NOTICE_LEAD_VIOLATION", "notices due must be SENT or ACKNOWLEDGED")
    wo["execution_status"] = "MOBILIZED"
    db.touch(wo)
    # bubble: plan APPROVED -> EXECUTING
    if plan["status"] == "APPROVED":
        plan["status"] = "EXECUTING"
        db.touch(plan)
        segment["rehab_status"] = "IN_PROGRESS"
        db.touch(segment)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/begin-work")
def begin_work(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    if wo["execution_status"] != "MOBILIZED":
        raise err_invalid_state("work order not MOBILIZED")
    _crew_gate(actor, wo)
    # if any bypass plan exists for this work order, it must be ACTIVE
    bypasses = [b for b in db.bypass_plans.values() if b["work_order_id"] == wo["id"]]
    if bypasses:
        active = [b for b in bypasses if b["status"] == "ACTIVE"]
        if not active:
            raise err_conflict("ERR_BYPASS_NOT_ACTIVE", "a bypass plan exists but is not ACTIVE")
    wo["execution_status"] = "IN_WORK"
    db.touch(wo)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/stand-down")
def stand_down(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    if wo["execution_status"] != "IN_WORK":
        raise err_invalid_state("work order not IN_WORK")
    _crew_gate(actor, wo)
    wo["execution_status"] = "MOBILIZED"
    db.touch(wo)
    # cascade: ACTIVE bypass -> DEMOBILIZED
    for b in db.bypass_plans.values():
        if b["work_order_id"] == wo["id"] and b["status"] == "ACTIVE":
            b["status"] = "DEMOBILIZED"
            db.touch(b)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/submit-punch")
def submit_punch(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    if wo["execution_status"] != "IN_WORK":
        raise err_invalid_state("work order not IN_WORK")
    _crew_gate(actor, wo)
    for li in db.line_items.values():
        if li["work_order_id"] == wo["id"] and li["installed_qty"] is None:
            raise err_conflict("ERR_QTY_MISSING", "every line item must have installed_qty set")
    wo["execution_status"] = "PUNCH_LIST"
    db.touch(wo)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/resume-work")
def resume_work(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    if wo["execution_status"] != "PUNCH_LIST":
        raise err_invalid_state("work order not PUNCH_LIST")
    _crew_gate(actor, wo)
    wo["execution_status"] = "IN_WORK"
    db.touch(wo)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


def _add_months(dt, months):
    """Add months to a datetime, clamping day-of-month."""
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    # days in target month
    if month == 12:
        next_first = dt.replace(year=year + 1, month=1, day=1)
    else:
        next_first = dt.replace(year=year, month=month + 1, day=1)
    this_first = dt.replace(year=year, month=month, day=1)
    days = (next_first - this_first).days
    day = min(dt.day, days)
    return dt.replace(year=year, month=month, day=day)


@bp.post("/sewer/work-orders/<id>/complete")
def complete(id):
    actor = get_actor()
    require_roles(actor, ["CrewLead"])
    wo = get_work_order(id)
    if wo["execution_status"] != "PUNCH_LIST":
        raise err_invalid_state("work order not PUNCH_LIST")
    _crew_gate(actor, wo)
    # bypass demobilized-or-closed
    for b in db.bypass_plans.values():
        if b["work_order_id"] == wo["id"] and b["status"] not in ("DEMOBILIZED", "CLOSED", "REJECTED"):
            raise err_conflict("ERR_BYPASS_STILL_ACTIVE", "bypass not demobilized/closed")
    plan = db.plans[wo["plan_id"]]
    segment = db.segments[plan["segment_id"]]
    if plan["method"] == "CIPP_LINING":
        # certified POST_CIPP inspection
        has_certified_post = any(
            i["segment_id"] == segment["id"] and i["purpose"] == "POST_CIPP" and i["status"] == "CERTIFIED"
            for i in db.inspections.values()
        )
        if not has_certified_post:
            raise err_conflict("ERR_POST_INSPECTION_REQUIRED", "CIPP completion requires certified POST_CIPP inspection")
        actives = [l for l in db.laterals.values() if l["segment_id"] == segment["id"] and l["active"]]
        if not all(l["reinstated"] for l in actives):
            raise err_conflict("ERR_LATERALS_OPEN", "every active lateral must be reinstated")
    # Stamp completion
    now = db.now_dt()
    wo["completed_at"] = _format_iso(now)
    district = db.districts[segment["district_id"]]
    wo["warranty_expires_at"] = _format_iso(_add_months(now, district["warranty_months"]))
    # Recompute final line cents for this WO
    for li in db.line_items.values():
        if li["work_order_id"] == wo["id"] and li["installed_qty"] is not None:
            li["final_line_cents"] = compute_line_cents(li["installed_qty"], li["unit_price_cents"])
            db.touch(li)
    wo["execution_status"] = "COMPLETED"
    db.touch(wo)
    # plan-level: if this is the last non-CANCELLED wo of the plan, complete plan
    siblings = [w for w in db.work_orders.values() if w["plan_id"] == plan["id"] and w["execution_status"] != "CANCELLED"]
    all_completed = all(w["execution_status"] == "COMPLETED" for w in siblings)
    if all_completed:
        recompute_plan_final(plan["id"])
        plan["status"] = "COMPLETED"
        db.touch(plan)
        district["budget_committed_cents"] = max(0, district["budget_committed_cents"] - plan["provisional_total_cents"])
        db.touch(district)
        segment["rehab_status"] = "REHABILITATED"
        segment["last_rehab_completed_at"] = _format_iso(now)
        db.touch(segment)
        if plan["method"] == "CIPP_LINING":
            for l in db.laterals.values():
                if l["segment_id"] == segment["id"] and l["active"]:
                    l["reinstated"] = False
                    db.touch(l)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/cancel")
def cancel(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    wo = get_work_order(id)
    if wo["execution_status"] not in ("ISSUED", "MOBILIZED"):
        raise err_invalid_state("work order not ISSUED/MOBILIZED")
    was_mobilized = wo["execution_status"] == "MOBILIZED"
    wo["execution_status"] = "CANCELLED"
    db.touch(wo)
    if was_mobilized:
        for b in db.bypass_plans.values():
            if b["work_order_id"] == wo["id"] and b["status"] in ("PROPOSED", "APPROVED", "ACTIVE"):
                b["status"] = "CLOSED"
                db.touch(b)
    # cancellation affects plan provisional (cancelled WOs excluded)
    recompute_plan_provisional(wo["plan_id"])
    sweep_notice_expiry()
    return success_object(wo_view(wo))


# ---------------------------------------------------------------------------
# Billing dimension
# ---------------------------------------------------------------------------

@bp.post("/sewer/work-orders/<id>/invoice")
def invoice(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    wo = get_work_order(id)
    if wo["billing_status"] != "UNBILLED":
        raise err_invalid_state("work order not UNBILLED")
    if wo["execution_status"] != "COMPLETED":
        raise err_conflict("ERR_NOT_COMPLETED", "invoicing requires execution COMPLETED")
    wo["billing_status"] = "INVOICED"
    db.touch(wo)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/void-invoice")
def void_invoice(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    wo = get_work_order(id)
    if wo["billing_status"] != "INVOICED":
        raise err_invalid_state("work order not INVOICED")
    wo["billing_status"] = "UNBILLED"
    db.touch(wo)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


@bp.post("/sewer/work-orders/<id>/mark-paid")
def mark_paid(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    wo = get_work_order(id)
    if wo["billing_status"] != "INVOICED":
        raise err_invalid_state("work order not INVOICED")
    wo["billing_status"] = "PAID"
    db.touch(wo)
    sweep_notice_expiry()
    return success_object(wo_view(wo))


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

@bp.post("/sewer/work-orders/<id>/line-items")
def create_line_item(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    wo = get_work_order(id)
    payload = body()
    pay_item_code = require_string(payload, "pay_item_code")
    scheduled = require_number(payload, "scheduled_qty")
    if scheduled <= 0:
        raise err_invalid_request("scheduled_qty must be > 0")
    price = require_int(payload, "unit_price_cents")
    if price <= 0:
        raise err_invalid_request("unit_price_cents must be > 0")
    expected = payload.get("expected_work_order_version")
    if expected is None:
        raise err_invalid_request("expected_work_order_version required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_work_order_version must be integer")
    if expected != wo["version"]:
        raise err_stale_version()
    prov = compute_line_cents(scheduled, price)
    ent = {
        "id": db.new_id(),
        "work_order_id": wo["id"],
        "pay_item_code": pay_item_code,
        "scheduled_qty": scheduled,
        "installed_qty": None,
        "unit_price_cents": price,
        "provisional_line_cents": prov,
        "final_line_cents": None,
    }
    db.stamp_new(ent)
    db.line_items[ent["id"]] = ent
    db.touch(wo)
    recompute_plan_provisional(wo["plan_id"])
    sweep_notice_expiry()
    return success_object(li_view(ent), status=201)


@bp.get("/sewer/work-orders/<id>/line-items")
def list_line_items(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer", "CrewLead"])
    wo = get_work_order(id)
    limit, offset = parse_pagination()
    items = [li for li in db.line_items.values() if li["work_order_id"] == wo["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([li_view(li) for li in page], limit, offset, total)


@bp.patch("/sewer/work-orders/<id>/line-items/<lineId>")
def update_line_item(id, lineId):
    actor = get_actor()
    require_roles(actor, ["CrewLead", "DistrictEngineer"])
    wo = get_work_order(id)
    li = db.line_items.get(lineId)
    if li is None or li["work_order_id"] != wo["id"]:
        raise err_not_found("line item not found on work order")
    payload = body()
    has_installed = "installed_qty" in payload and payload["installed_qty"] is not None
    has_sched_or_price = ("scheduled_qty" in payload) or ("unit_price_cents" in payload)
    if has_installed:
        # CrewLead (or DE per shared PATCH) may set installed_qty while IN_WORK/PUNCH_LIST
        if wo["execution_status"] not in ("IN_WORK", "PUNCH_LIST"):
            raise err_invalid_state("installed_qty settable only while IN_WORK or PUNCH_LIST")
        if actor.role == "CrewLead":
            _crew_gate(actor, wo)
        v = payload["installed_qty"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err_invalid_request("installed_qty must be a number")
        if v < 0:
            raise err_invalid_request("installed_qty must be >= 0")
        li["installed_qty"] = v
        li["final_line_cents"] = compute_line_cents(v, li["unit_price_cents"])
    if has_sched_or_price:
        # corrections only while ISSUED; only DistrictEngineer per PRD §3.5
        if wo["execution_status"] != "ISSUED":
            raise err_invalid_state("scheduled_qty/unit_price_cents correctable only while ISSUED")
        if actor.role != "DistrictEngineer":
            raise err_unauthorized("only DistrictEngineer may correct scheduled_qty/unit_price_cents")
        if "scheduled_qty" in payload:
            v = payload["scheduled_qty"]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise err_invalid_request("scheduled_qty must be a positive number")
            li["scheduled_qty"] = v
        if "unit_price_cents" in payload:
            v = payload["unit_price_cents"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise err_invalid_request("unit_price_cents must be a positive integer")
            li["unit_price_cents"] = v
        li["provisional_line_cents"] = compute_line_cents(li["scheduled_qty"], li["unit_price_cents"])
    if not has_installed and not has_sched_or_price:
        raise err_invalid_request("no updatable field supplied")
    db.touch(li)
    recompute_plan_provisional(wo["plan_id"])
    if wo["execution_status"] == "COMPLETED":
        recompute_plan_final(wo["plan_id"])
    sweep_notice_expiry()
    return success_object(li_view(li))
