"""Work orders, dispatch/SLA and soft-service shifts."""

from decimal import Decimal

import calc
import domain
import serializers
import validate as v
from auth import require
from calc import D
from envelope import list_response, object_response, pagination
from errors import fail
from flask import Blueprint, g
from store import base_fields, db, ordered, touch

bp = Blueprint("work", __name__)

WO_TYPES = {"CORRECTIVE", "PREVENTIVE", "SOFT_SERVICE"}
PRIORITIES = {"P1", "P2", "P3", "P4"}
WO_STATUSES = {"NEW", "DISPATCHED", "IN_PROGRESS", "PENDING_QA", "CLOSED", "CANCELLED"}
BILLING_STATUSES = {"PENDING", "INVOICED", "SETTLED_CHARGEBACK", "WAIVED"}
DISPATCH_STATUSES = {"OFFERED", "ACCEPTED", "DECLINED", "COMPLETED", "CANCELLED"}
SHIFT_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "MISSED", "CANCELLED"}
SERVICE_TYPES = {"JANITORIAL", "SECURITY"}
QA_OUTCOMES = {"PASS", "FAIL"}
FUNDABLE_PROJECT_STATUSES = ("APPROVED", "IN_FLIGHT")


def get_work_order(work_order_id):
    row = db.work_orders.get(work_order_id)
    if row is None:
        fail("ERR_WORK_ORDER_NOT_FOUND", "Work order %s does not exist." % work_order_id)
    return row


def get_dispatch(dispatch_id):
    row = db.dispatches.get(dispatch_id)
    if row is None:
        fail("ERR_DISPATCH_NOT_FOUND", "Dispatch %s does not exist." % dispatch_id)
    return row


def get_shift(shift_id):
    row = db.shifts.get(shift_id)
    if row is None:
        fail("ERR_SHIFT_NOT_FOUND", "Shift %s does not exist." % shift_id)
    return row


def _refresh_project(project_id):
    if project_id:
        project = db.projects.get(project_id)
        if project is not None:
            domain.recompute_project(project)


def _recompute_scores_for_work_order(work_order):
    vendor_ids = {d["vendor_id"] for d in domain.wo_dispatches(work_order["id"])}
    for vendor_id in vendor_ids:
        vendor = db.vendors.get(vendor_id)
        if vendor is not None:
            domain.recompute_vendor_scores(vendor)


# ---------------------------------------------------------------------------
# Work orders
# ---------------------------------------------------------------------------
@bp.post("/work-orders")
@require("PlatformAdmin", "FacilityManager")
def create_work_order():
    data = v.body()
    building_id = v.string(data, "building_id")
    wo_type = v.enum(data, "wo_type", WO_TYPES)
    priority = v.enum(data, "priority", PRIORITIES)
    est_hours = v.number(data, "estimated_labor_hours", ge=0)
    est_parts = v.number(data, "estimated_parts_cost", ge=0)
    asset_id = v.string(data, "asset_id", required=False)
    pm_plan_id = v.string(data, "pm_plan_id", required=False)
    funding_project_id = v.string(data, "funding_project_id", required=False)
    chargeable = v.boolean(data, "chargeable", required=False, default=True)

    # step 5 -- body foreign keys
    building = db.buildings.get(building_id)
    if building is None:
        fail("ERR_BUILDING_NOT_FOUND", "Building %s does not exist." % building_id)
    asset = None
    if asset_id is not None:
        asset = db.assets.get(asset_id)
        if asset is None:
            fail("ERR_ASSET_NOT_FOUND", "Asset %s does not exist." % asset_id)
    plan = None
    if pm_plan_id is not None:
        plan = db.pm_plans.get(pm_plan_id)
        if plan is None:
            fail("ERR_PM_PLAN_NOT_FOUND", "PM plan %s does not exist." % pm_plan_id)
    project = None
    if funding_project_id is not None:
        project = db.projects.get(funding_project_id)
        if project is None:
            fail(
                "ERR_PROJECT_NOT_FOUND",
                "Capital project %s does not exist." % funding_project_id,
            )

    # step 10 -- referenced-parent state
    if asset is not None and asset["status"] == "RETIRED":
        fail("ERR_ASSET_RETIRED", "The asset is retired and can no longer take work.")
    if project is not None and project["status"] not in FUNDABLE_PROJECT_STATUSES:
        fail("ERR_PROJECT_NOT_FUNDABLE", "The capital project cannot fund work orders.")

    # step 11 -- building posture gate
    posture = building["operating_posture"]
    if posture == "FROZEN" and not (wo_type == "CORRECTIVE" and priority == "P1"):
        fail(
            "ERR_BUILDING_FROZEN",
            "The building is FROZEN; only CORRECTIVE P1 orders may be raised.",
        )
    if posture == "RESTRICTED" and priority in ("P3", "P4"):
        fail(
            "ERR_BUILDING_RESTRICTED",
            "The building is RESTRICTED; P3 and P4 orders may not be raised.",
        )

    # step 14 -- cross-aggregate coherence
    if plan is not None and plan["asset_id"] != asset_id:
        fail("ERR_PM_PLAN_ASSET_MISMATCH", "The PM plan covers a different asset.")
    if asset is not None and asset["building_id"] != building["id"]:
        fail("ERR_ASSET_BUILDING_MISMATCH", "The asset sits in a different building.")

    estimated_amount = calc.provisional_estimate(
        est_hours, est_parts, calc.STANDARD_LABOR_RATE, priority, db.clock
    )

    # step 19 -- capital funding
    if project is not None and D(project["remaining_amount"]) < estimated_amount:
        fail(
            "ERR_PROJECT_BUDGET_EXCEEDED",
            "The capital project's remaining amount cannot cover this estimate.",
        )

    row = base_fields()
    row.update(
        {
            "building_id": building["id"],
            "asset_id": asset_id,
            "pm_plan_id": pm_plan_id,
            "funding_project_id": funding_project_id,
            "statement_id": None,
            "wo_type": wo_type,
            "priority": priority,
            "chargeable": chargeable,
            "estimated_labor_hours": est_hours,
            "estimated_parts_cost": est_parts,
            "actual_labor_hours": None,
            "actual_parts_cost": None,
            "estimated_amount": estimated_amount,
            "billable_amount": None,
            "status": "NEW",
            "billing_status": "PENDING",
            "failed_qa_count": 0,
            "dispatched_at": None,
            "sla_response_due_at": None,
            "sla_resolve_due_at": None,
            "sla_state": "WITHIN",
            "closed_at": None,
        }
    )
    db.work_orders[row["id"]] = row

    if project is not None:
        if project["status"] == "APPROVED":
            project["status"] = "IN_FLIGHT"
            touch(project)
        domain.recompute_project(project)

    domain.recompute_building(building)
    return object_response(serializers.work_order(row), 201)


@bp.get("/work-orders/<work_order_id>")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "VendorTech")
def read_work_order(work_order_id):
    return object_response(serializers.work_order(get_work_order(work_order_id)))


@bp.get("/work-orders")
@require("PlatformAdmin", "FacilityManager", "FinanceController")
def list_work_orders():
    status = v.query_enum("status", WO_STATUSES)
    billing_status = v.query_enum("billing_status", BILLING_STATUSES)
    building_id = v.query_str("building_id")
    asset_id = v.query_str("asset_id")
    pm_plan_id = v.query_str("pm_plan_id")
    funding_project_id = v.query_str("funding_project_id")
    statement_id = v.query_str("statement_id")
    limit, offset = pagination()

    rows = list(db.work_orders.values())
    if building_id:
        rows = [w for w in rows if w["building_id"] == building_id]
    if asset_id:
        rows = [w for w in rows if w["asset_id"] == asset_id]
    if pm_plan_id:
        rows = [w for w in rows if w["pm_plan_id"] == pm_plan_id]
    if funding_project_id:
        rows = [w for w in rows if w["funding_project_id"] == funding_project_id]
    if statement_id:
        rows = [w for w in rows if w["statement_id"] == statement_id]
    if status:
        rows = [w for w in rows if w["status"] == status]
    if billing_status:
        rows = [w for w in rows if w["billing_status"] == billing_status]
    return list_response(
        [serializers.work_order(w) for w in ordered(rows)], limit, offset
    )


@bp.post("/work-orders/<work_order_id>/dispatches")
@require("PlatformAdmin", "FacilityManager")
def create_dispatch(work_order_id):
    data = v.body()
    vendor_id = v.string(data, "vendor_id")
    expected_version = v.integer(data, "expected_work_order_version")

    wo = get_work_order(work_order_id)

    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        fail("ERR_VENDOR_NOT_FOUND", "Vendor %s does not exist." % vendor_id)

    # step 8 -- optimistic concurrency
    if expected_version != wo["version"]:
        fail("ERR_STALE_VERSION", "The work order has been modified since it was read.")

    # step 9 -- transition legality
    if wo["status"] != "NEW":
        fail("ERR_WORK_ORDER_NOT_OPEN", "Only a NEW work order may be dispatched.")

    # step 12 -- vendor eligibility
    if vendor["status"] == "SUSPENDED":
        fail("ERR_VENDOR_SUSPENDED", "The vendor is suspended.")

    # step 13 -- trade competence
    if wo["asset_id"] is not None:
        asset = db.assets.get(wo["asset_id"])
        if asset is not None and vendor["trade"] != asset["category"]:
            fail(
                "ERR_VENDOR_TRADE_MISMATCH",
                "The vendor's trade does not match the asset's category.",
            )

    dispatched_at = db.clock
    new_estimate = calc.provisional_estimate(
        wo["estimated_labor_hours"],
        wo["estimated_parts_cost"],
        vendor["hourly_rate"],
        wo["priority"],
        dispatched_at,
    )

    # step 19 -- capital funding (the old hold is about to be handed back)
    project = db.projects.get(wo["funding_project_id"]) if wo["funding_project_id"] else None
    if project is not None:
        available = D(project["remaining_amount"]) + D(wo["estimated_amount"])
        if available < new_estimate:
            fail(
                "ERR_PROJECT_BUDGET_EXCEEDED",
                "The capital project's remaining amount cannot cover this estimate.",
            )

    # supersede any still-OFFERED dispatch on this order
    for existing in ordered(domain.wo_dispatches(wo["id"])):
        if existing["status"] == "OFFERED":
            existing["status"] = "CANCELLED"
            touch(existing)

    row = base_fields()
    row.update(
        {
            "work_order_id": wo["id"],
            "vendor_id": vendor["id"],
            "status": "OFFERED",
            "dispatched_at": dispatched_at,
            "accepted_at": None,
            "completed_at": None,
            "response_minutes": None,
            "resolve_minutes": None,
            "sla_response_met": None,
            "sla_resolve_met": None,
            "penalty_pct": calc.D(0),
            "actual_labor_hours": None,
            "actual_parts_cost": None,
        }
    )
    db.dispatches[row["id"]] = row

    wo["status"] = "DISPATCHED"
    wo["dispatched_at"] = dispatched_at
    wo["sla_response_due_at"] = calc.add_minutes(
        dispatched_at, vendor["sla_response_minutes"]
    )
    wo["sla_resolve_due_at"] = calc.add_minutes(
        dispatched_at, vendor["sla_resolve_minutes"]
    )
    wo["estimated_amount"] = new_estimate
    touch(wo)

    if project is not None:
        if project["status"] == "APPROVED":
            project["status"] = "IN_FLIGHT"
            touch(project)
        domain.recompute_project(project)

    return object_response(serializers.dispatch(row), 201)


@bp.post("/work-orders/<work_order_id>/qa")
@require("PlatformAdmin", "FacilityManager")
def qa_work_order(work_order_id):
    data = v.body()
    outcome = v.enum(data, "outcome", QA_OUTCOMES)

    wo = get_work_order(work_order_id)
    if wo["status"] != "PENDING_QA":
        fail("ERR_WORK_ORDER_NOT_OPEN", "The work order is not awaiting QA.")

    if outcome == "FAIL":
        wo["failed_qa_count"] += 1
        for dispatch in ordered(domain.wo_dispatches(wo["id"])):
            if dispatch["status"] == "COMPLETED":
                dispatch["status"] = "ACCEPTED"
                dispatch["completed_at"] = None
                dispatch["resolve_minutes"] = None
                dispatch["sla_resolve_met"] = None
                dispatch["penalty_pct"] = calc.D(0)
                touch(dispatch)
        wo["billable_amount"] = None
        wo["status"] = "IN_PROGRESS"
        touch(wo)
        _recompute_scores_for_work_order(wo)
        _refresh_project(wo["funding_project_id"])
        return object_response(serializers.work_order(wo))

    # PASS
    wo["status"] = "CLOSED"
    wo["closed_at"] = db.clock
    if wo["chargeable"] is False:
        wo["billing_status"] = "WAIVED"
    touch(wo)

    asset = db.assets.get(wo["asset_id"]) if wo["asset_id"] else None
    if wo["wo_type"] == "CORRECTIVE" and asset is not None:
        if asset["status"] == "OUT_OF_SERVICE":
            asset["status"] = "IN_SERVICE"
            touch(asset)
    elif wo["wo_type"] == "PREVENTIVE" and asset is not None:
        asset["runtime_hours"] = 0
        asset["failure_count"] = max(0, asset["failure_count"] - 1)
        asset["last_pm_at"] = db.clock
        asset["condition_score"] = calc.condition_score(0, asset["failure_count"])
        touch(asset)
        if wo["pm_plan_id"]:
            plan = db.pm_plans.get(wo["pm_plan_id"])
            if plan is not None and plan["next_due_at"] is not None:
                from datetime import timedelta

                plan["next_due_at"] = plan["next_due_at"] + timedelta(
                    days=int(plan["interval_days"])
                )
                touch(plan)

    _recompute_scores_for_work_order(wo)
    _refresh_project(wo["funding_project_id"])

    building = db.buildings.get(wo["building_id"])
    if building is not None:
        domain.recompute_building(building)

    return object_response(serializers.work_order(wo))


@bp.post("/work-orders/<work_order_id>/cancel")
@require("PlatformAdmin", "FacilityManager")
def cancel_work_order(work_order_id):
    wo = get_work_order(work_order_id)
    if wo["status"] not in ("NEW", "DISPATCHED"):
        fail("ERR_WORK_ORDER_NOT_OPEN", "Only a NEW or DISPATCHED order may be cancelled.")

    if wo["status"] == "DISPATCHED":
        for dispatch in ordered(domain.wo_dispatches(wo["id"])):
            if dispatch["status"] in ("OFFERED", "ACCEPTED"):
                dispatch["status"] = "CANCELLED"
                touch(dispatch)

    wo["status"] = "CANCELLED"
    touch(wo)

    _refresh_project(wo["funding_project_id"])

    building = db.buildings.get(wo["building_id"])
    if building is not None:
        domain.recompute_building(building)

    return object_response(serializers.work_order(wo))


# ---------------------------------------------------------------------------
# Dispatches
# ---------------------------------------------------------------------------
@bp.get("/dispatches/<dispatch_id>")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "VendorTech")
def read_dispatch(dispatch_id):
    return object_response(serializers.dispatch(get_dispatch(dispatch_id)))


@bp.get("/dispatches")
@require("PlatformAdmin", "FacilityManager", "FinanceController", "VendorTech")
def list_dispatches():
    status = v.query_enum("status", DISPATCH_STATUSES)
    work_order_id = v.query_str("work_order_id")
    vendor_id = v.query_str("vendor_id")
    limit, offset = pagination()

    rows = list(db.dispatches.values())
    if work_order_id:
        rows = [d for d in rows if d["work_order_id"] == work_order_id]
    if vendor_id:
        rows = [d for d in rows if d["vendor_id"] == vendor_id]
    if status:
        rows = [d for d in rows if d["status"] == status]
    return list_response([serializers.dispatch(d) for d in ordered(rows)], limit, offset)


@bp.post("/dispatches/<dispatch_id>/accept")
@require("VendorTech")
def accept_dispatch(dispatch_id):
    dispatch = get_dispatch(dispatch_id)
    if dispatch["vendor_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This dispatch belongs to another vendor.")
    if dispatch["status"] != "OFFERED":
        fail("ERR_DISPATCH_NOT_ACTIONABLE", "The dispatch is not OFFERED.")

    wo = db.work_orders[dispatch["work_order_id"]]
    accepted_at = db.clock
    dispatch["status"] = "ACCEPTED"
    dispatch["accepted_at"] = accepted_at
    dispatch["response_minutes"] = calc.whole_minutes(
        dispatch["dispatched_at"], accepted_at
    )
    met = accepted_at <= wo["sla_response_due_at"]
    dispatch["sla_response_met"] = met
    touch(dispatch)

    wo["status"] = "IN_PROGRESS"
    if not met:
        wo["sla_state"] = "RESPONSE_BREACHED"
    touch(wo)

    return object_response(serializers.dispatch(dispatch))


@bp.post("/dispatches/<dispatch_id>/decline")
@require("VendorTech")
def decline_dispatch(dispatch_id):
    data = v.body()
    v.string(data, "reason", required=False)

    dispatch = get_dispatch(dispatch_id)
    if dispatch["vendor_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This dispatch belongs to another vendor.")
    if dispatch["status"] != "OFFERED":
        fail("ERR_DISPATCH_NOT_ACTIONABLE", "The dispatch is not OFFERED.")

    dispatch["status"] = "DECLINED"
    touch(dispatch)

    wo = db.work_orders[dispatch["work_order_id"]]
    wo["status"] = "NEW"
    wo["dispatched_at"] = None
    wo["sla_response_due_at"] = None
    wo["sla_resolve_due_at"] = None
    wo["estimated_amount"] = calc.provisional_estimate(
        wo["estimated_labor_hours"],
        wo["estimated_parts_cost"],
        calc.STANDARD_LABOR_RATE,
        wo["priority"],
        db.clock,
    )
    touch(wo)

    _refresh_project(wo["funding_project_id"])

    return object_response(serializers.dispatch(dispatch))


@bp.post("/dispatches/<dispatch_id>/complete")
@require("VendorTech")
def complete_dispatch(dispatch_id):
    data = v.body()
    actual_hours = v.number(data, "actual_labor_hours")
    actual_parts = v.number(data, "actual_parts_cost")

    dispatch = get_dispatch(dispatch_id)
    if dispatch["vendor_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This dispatch belongs to another vendor.")
    if dispatch["status"] != "ACCEPTED":
        fail("ERR_DISPATCH_NOT_ACTIONABLE", "The dispatch is not ACCEPTED.")

    wo = db.work_orders[dispatch["work_order_id"]]
    vendor = db.vendors[dispatch["vendor_id"]]
    completed_at = db.clock

    # L1 -- dispatch + work order
    dispatch["status"] = "COMPLETED"
    dispatch["completed_at"] = completed_at
    dispatch["resolve_minutes"] = calc.whole_minutes(
        dispatch["dispatched_at"], completed_at
    )
    resolve_met = completed_at <= wo["sla_resolve_due_at"]
    dispatch["sla_resolve_met"] = resolve_met
    dispatch["actual_labor_hours"] = actual_hours
    dispatch["actual_parts_cost"] = actual_parts
    dispatch["penalty_pct"] = calc.penalty_pct_for(
        dispatch["sla_response_met"], resolve_met
    )
    touch(dispatch)

    wo["actual_labor_hours"] = actual_hours
    wo["actual_parts_cost"] = actual_parts
    if not resolve_met:
        wo["sla_state"] = "RESOLVE_BREACHED"
    elif dispatch["sla_response_met"] is False:
        wo["sla_state"] = "RESPONSE_BREACHED"
    wo["billable_amount"] = calc.final_settlement(
        actual_hours,
        actual_parts,
        vendor["hourly_rate"],
        wo["priority"],
        wo["dispatched_at"],
        dispatch["penalty_pct"],
    )
    wo["status"] = "PENDING_QA"
    touch(wo)

    # L2 -- vendor counters
    breached = (dispatch["sla_response_met"] is False) or (resolve_met is False)
    vendor["completed_dispatch_count"] += 1
    touch(vendor)
    domain.recompute_vendor_scores(vendor)

    # L3 + L4 -- strike ladder and the suspension cascade
    if breached:
        domain.apply_strike(vendor)

    _refresh_project(wo["funding_project_id"])

    return object_response(serializers.dispatch(dispatch))


# ---------------------------------------------------------------------------
# Soft-service shifts
# ---------------------------------------------------------------------------
@bp.post("/soft-service-shifts")
@require("PlatformAdmin", "FacilityManager")
def create_shift():
    data = v.body()
    building_id = v.string(data, "building_id")
    vendor_id = v.string(data, "vendor_id")
    zone_space_id = v.string(data, "zone_space_id")
    service_type = v.enum(data, "service_type", SERVICE_TYPES)
    start_at = v.datetime_field(data, "start_at")
    end_at = v.datetime_field(data, "end_at")
    planned_headcount = v.integer(data, "planned_headcount", ge=1)
    if not end_at > start_at:
        fail("ERR_INVALID_REQUEST", "end_at must be strictly later than start_at.")

    building = db.buildings.get(building_id)
    if building is None:
        fail("ERR_BUILDING_NOT_FOUND", "Building %s does not exist." % building_id)
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        fail("ERR_VENDOR_NOT_FOUND", "Vendor %s does not exist." % vendor_id)
    space = db.spaces.get(zone_space_id)
    if space is None:
        fail("ERR_SPACE_NOT_FOUND", "Space %s does not exist." % zone_space_id)

    # step 11 -- posture gate
    if building["operating_posture"] == "FROZEN":
        fail("ERR_BUILDING_FROZEN", "The building is FROZEN; no shift may be scheduled.")

    # step 13 -- trade competence
    if vendor["trade"] != service_type:
        fail("ERR_VENDOR_TRADE_MISMATCH", "The vendor's trade does not match the service type.")

    # step 14 -- cross-aggregate coherence
    if space["building_id"] != building["id"]:
        fail("ERR_SPACE_BUILDING_MISMATCH", "The zone space sits in a different building.")

    # step 15 -- shift overlap on the VENDOR, half-open [start_at, end_at)
    for existing in db.shifts.values():
        if existing["vendor_id"] != vendor["id"]:
            continue
        if existing["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if start_at < existing["end_at"] and existing["start_at"] < end_at:
            fail("ERR_SHIFT_OVERLAP", "The vendor already holds an intersecting shift.")

    row = base_fields()
    row.update(
        {
            "building_id": building["id"],
            "vendor_id": vendor["id"],
            "zone_space_id": space["id"],
            "service_type": service_type,
            "start_at": start_at,
            "end_at": end_at,
            "planned_headcount": planned_headcount,
            "actual_headcount": None,
            "status": "SCHEDULED",
        }
    )
    db.shifts[row["id"]] = row
    return object_response(serializers.shift(row), 201)


@bp.get("/soft-service-shifts/<shift_id>")
@require("PlatformAdmin", "FacilityManager", "VendorTech")
def read_shift(shift_id):
    return object_response(serializers.shift(get_shift(shift_id)))


@bp.get("/soft-service-shifts")
@require("PlatformAdmin", "FacilityManager", "VendorTech")
def list_shifts():
    status = v.query_enum("status", SHIFT_STATUSES)
    building_id = v.query_str("building_id")
    vendor_id = v.query_str("vendor_id")
    zone_space_id = v.query_str("zone_space_id")
    limit, offset = pagination()

    rows = list(db.shifts.values())
    if building_id:
        rows = [s for s in rows if s["building_id"] == building_id]
    if vendor_id:
        rows = [s for s in rows if s["vendor_id"] == vendor_id]
    if zone_space_id:
        rows = [s for s in rows if s["zone_space_id"] == zone_space_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return list_response([serializers.shift(s) for s in ordered(rows)], limit, offset)


@bp.post("/soft-service-shifts/<shift_id>/complete")
@require("VendorTech")
def complete_shift(shift_id):
    data = v.body()
    actual_headcount = v.integer(data, "actual_headcount")

    shift = get_shift(shift_id)
    if shift["vendor_id"] != g.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This shift belongs to another vendor.")
    if shift["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_SHIFT_NOT_SCHEDULED", "The shift cannot be completed from its status.")

    shift["status"] = "COMPLETED"
    shift["actual_headcount"] = actual_headcount
    touch(shift)
    return object_response(serializers.shift(shift))
