"""Work order endpoints: create, read, list, and the lifecycle actions
(submit-quote, begin-installation, begin-testing, complete, cancel,
acknowledge-overage)."""
import math

from flask import Blueprint, request

import clock
import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    opt_int,
    pagination_args,
    paginate,
    req_dt,
    req_int,
    req_num,
    req_str,
    require_role,
)
from response import success
from serializers import ser_work_order
from services.core import (
    WO_TERMINAL,
    OVERAGE_ACK_THRESHOLD_DAYS,
    bay_window_conflict,
    check_customer_ownership,
    children_of,
    quote_total,
    recompute_work_order,
    set_aircraft_availability,
)
from util import add_months

bp = Blueprint("work_orders", __name__)


def _get_wo(workOrderId):
    wo = db.work_orders.get(workOrderId)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")
    return wo


@bp.post("/avionics/work-orders")
def create_work_order():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    aircraft_id = req_str(b, "aircraft_id")
    scope_description = req_str(b, "scope_description")
    estimated_downtime_days = req_int(b, "estimated_downtime_days")
    quoted_labor_hours = req_num(b, "quoted_labor_hours")
    bay_code = req_str(b, "bay_code")
    bay_window_start = req_dt(b, "bay_window_start")
    bay_window_end = req_dt(b, "bay_window_end")
    if not (bay_window_end > bay_window_start):
        errors.raise_err(errors.ERR_VALIDATION, "bay_window_end must be after bay_window_start")
    warranty_term_months = opt_int(b, "warranty_term_months", 12)
    software_subscription_months = opt_int(b, "software_subscription_months", 12)

    # existence (priority 4)
    aircraft = db.aircraft.get(aircraft_id)
    if aircraft is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Aircraft not found")

    # temporal (priority 7): bay half-open overlap vs other non-terminal orders
    if bay_window_conflict(bay_code, bay_window_start, bay_window_end):
        errors.raise_err(
            errors.ERR_BAY_WINDOW_CONFLICT,
            "Bay window overlaps another non-terminal work order on this bay",
        )

    # capacity (priority 9): one open work order per aircraft
    if any(
        w.status not in WO_TERMINAL
        for w in db.work_orders.values()
        if w.aircraft_id == aircraft_id
    ):
        errors.raise_err(errors.ERR_AIRCRAFT_BUSY, "Aircraft already has an open work order")

    wo = db.new_entity(
        aircraft_id=aircraft_id,
        scope_description=scope_description,
        estimated_downtime_days=estimated_downtime_days,
        quoted_labor_hours=quoted_labor_hours,
        bay_code=bay_code,
        bay_window_start=bay_window_start,
        bay_window_end=bay_window_end,
        status="DRAFT",
        inducted_at=None,
        completed_at=None,
        actual_downtime_days=None,
        downtime_overage_days=None,
        overage_acknowledged=False,
        parts_pending_count=0,
        tasks_unverified_count=0,
        total_actual_labor_hours=0.0,
        total_billed_labor_cents=0,
        quoted_total_cents=None,
        warranty_term_months=warranty_term_months,
        software_subscription_months=software_subscription_months,
        warranty_expires_at=None,
        subscription_expires_at=None,
    )
    db.work_orders[wo.id] = wo
    # creation flips the aircraft AVAILABLE -> IN_SHOP
    set_aircraft_availability(aircraft_id)
    return success(ser_work_order(wo), 201)


@bp.get("/avionics/work-orders/<workOrderId>")
def get_work_order(workOrderId):
    authenticate()
    return success(ser_work_order(_get_wo(workOrderId)), 200)


@bp.get("/avionics/work-orders")
def list_work_orders():
    authenticate()
    limit, offset = pagination_args()
    aircraft_id = request.args.get("aircraft_id")
    status = request.args.get("status")
    items = sorted(db.work_orders.values(), key=lambda w: w._seq)
    if aircraft_id is not None:
        items = [w for w in items if w.aircraft_id == aircraft_id]
    if status is not None:
        items = [w for w in items if w.status == status]
    page, meta = paginate([ser_work_order(w) for w in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/work-orders/<workOrderId>/submit-quote")
def submit_quote(workOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    wo = _get_wo(workOrderId)
    # state (priority 5)
    if wo.status != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Work order is not in DRAFT")
    # lineage (priority 8): needs a design still in DRAFT or SUBMITTED
    usable = [
        d
        for d in children_of(db.panel_designs, wo.id)
        if d.status in ("DRAFT", "SUBMITTED")
    ]
    if not usable:
        errors.raise_err(
            errors.ERR_NO_PANEL_DESIGN,
            "No non-superseded panel design available for quoting",
        )
    wo.quoted_total_cents = quote_total(wo)
    wo.status = "PENDING_APPROVAL"
    touch(wo)
    return success(ser_work_order(wo), 200)


@bp.post("/avionics/work-orders/<workOrderId>/begin-installation")
def begin_installation(workOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    wo = _get_wo(workOrderId)
    if wo.status not in ("APPROVED", "PARTS_PENDING"):
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Work order must be APPROVED or PARTS_PENDING to begin installation",
        )
    if wo.parts_pending_count != 0:
        errors.raise_err(errors.ERR_PARTS_PENDING, "Equipment orders are still outstanding")
    wo.inducted_at = clock.now()
    wo.status = "INSTALLATION"
    touch(wo)
    return success(ser_work_order(wo), 200)


@bp.post("/avionics/work-orders/<workOrderId>/begin-testing")
def begin_testing(workOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    wo = _get_wo(workOrderId)
    if wo.status != "INSTALLATION":
        errors.raise_err(errors.ERR_INVALID_STATE, "Work order is not in INSTALLATION")
    # gates checked in order: ERR_NO_INSTALL_TASKS, then ERR_TASKS_UNVERIFIED.
    # The first gate fires only when the work order has no verified task and
    # none in flight toward verification (nothing to test); a work order with
    # tasks still in PLANNED/IN_PROGRESS/COMPLETED falls to the second gate.
    tasks = children_of(db.install_tasks, wo.id)
    has_verified = any(t.status == "VERIFIED" for t in tasks)
    if not has_verified and wo.tasks_unverified_count == 0:
        errors.raise_err(errors.ERR_NO_INSTALL_TASKS, "No verified install task exists")
    if wo.tasks_unverified_count != 0:
        errors.raise_err(errors.ERR_TASKS_UNVERIFIED, "Install tasks remain unverified")
    wo.status = "TESTING"
    touch(wo)
    return success(ser_work_order(wo), 200)


@bp.post("/avionics/work-orders/<workOrderId>/complete")
def complete_work_order(workOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    wo = _get_wo(workOrderId)
    if wo.status != "TESTING":
        errors.raise_err(errors.ERR_INVALID_STATE, "Work order is not in TESTING")

    # safety/compliance gates in fixed order (priority 6): tests, regulatory, W&B
    events = children_of(db.test_events, wo.id)
    ground_ok = any(e.test_kind == "GROUND" and e.status == "PASSED" for e in events)
    flight_ok = any(e.test_kind == "FLIGHT" and e.status == "PASSED" for e in events)
    if not (ground_ok and flight_ok):
        errors.raise_err(
            errors.ERR_TESTS_NOT_PASSED,
            "Requires one PASSED ground test and one PASSED flight test",
        )
    if not any(
        p.status == "APPROVED" for p in children_of(db.regulatory_packages, wo.id)
    ):
        errors.raise_err(
            errors.ERR_REGULATORY_NOT_APPROVED, "No approved regulatory package"
        )
    if not any(
        r.status == "ACCEPTED" for r in children_of(db.wb_revisions, wo.id)
    ):
        errors.raise_err(errors.ERR_WB_NOT_ACCEPTED, "No accepted weight & balance revision")

    # temporal gate (priority 7): unacknowledged downtime overage of >= 5 days
    now = clock.now()
    elapsed_days = math.floor((now - wo.inducted_at).total_seconds() / 86400)
    if (
        elapsed_days - wo.estimated_downtime_days >= OVERAGE_ACK_THRESHOLD_DAYS
        and not wo.overage_acknowledged
    ):
        errors.raise_err(
            errors.ERR_DOWNTIME_OVERAGE_UNACKED,
            "Downtime overage of 5 or more days requires customer acknowledgement",
        )

    wo.completed_at = now
    wo.actual_downtime_days = elapsed_days
    wo.downtime_overage_days = elapsed_days - wo.estimated_downtime_days
    wo.warranty_expires_at = add_months(now, wo.warranty_term_months)
    wo.subscription_expires_at = add_months(now, wo.software_subscription_months)
    wo.status = "COMPLETED"
    touch(wo)
    set_aircraft_availability(wo.aircraft_id)
    return success(ser_work_order(wo), 200)


@bp.post("/avionics/work-orders/<workOrderId>/cancel")
def cancel_work_order(workOrderId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    wo = _get_wo(workOrderId)
    if wo.status in WO_TERMINAL:
        errors.raise_err(errors.ERR_INVALID_STATE, "Work order is terminal")

    for o in children_of(db.equipment_orders, wo.id):
        if o.status in ("PLANNED", "ORDERED"):
            o.status = "CANCELLED"
            touch(o)
    for t in children_of(db.install_tasks, wo.id):
        if t.status in ("PLANNED", "IN_PROGRESS", "COMPLETED"):
            t.status = "VOIDED"
            touch(t)
    for e in children_of(db.test_events, wo.id):
        if e.status in ("SCHEDULED", "FAILED"):
            e.status = "CANCELLED"
            touch(e)
    for d in children_of(db.panel_designs, wo.id):
        if d.status in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED"):
            d.status = "SUPERSEDED"
            touch(d)

    recompute_work_order(wo)
    wo.status = "CANCELLED"
    touch(wo)
    set_aircraft_availability(wo.aircraft_id)
    return success(ser_work_order(wo), 200)


@bp.post("/avionics/work-orders/<workOrderId>/acknowledge-overage")
def acknowledge_overage(workOrderId):
    uid, role = authenticate()
    require_role(role, {"Customer"})
    wo = db.work_orders.get(workOrderId)
    if wo is not None:
        # ownership (priority 2) is evaluated as soon as the resource is loaded
        check_customer_ownership(wo, uid)
    body()  # no input fields; parse errors still surface as ERR_VALIDATION
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")
    if wo.status in WO_TERMINAL:
        errors.raise_err(errors.ERR_INVALID_STATE, "Work order is terminal")
    wo.overage_acknowledged = True
    touch(wo)
    return success(ser_work_order(wo), 200)
