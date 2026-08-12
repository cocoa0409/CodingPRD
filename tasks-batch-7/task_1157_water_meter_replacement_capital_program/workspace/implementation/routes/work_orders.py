"""Work order endpoints (PRD 3.3, 3.5, 3.7): intake, assign, swap, reconcile,
rework, close, cancel."""
import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import (
    ALL_ROLES,
    check_contractor_ownership,
    require_roles,
)
from response import ok_object
from services.core import (
    FACTORY_INITIAL_READ_MAX_CCF,
    OPEN_COMPLAINT_STATES,
    OPEN_WO_STATES,
    account_return_to_eligible_if_clear,
    get_or_404,
    list_page,
    ser_work_order,
    swap_trueup_measured,
    swap_trueup_prorated,
    wave_counts,
    wo_cancel_cascade,
)
from flask import Blueprint, g, request
from validate import body, req_int, req_str

bp = Blueprint("work_orders", __name__)

ASSIGNABLE_STATES = ("CREATED", "NOTIFIED", "SCHEDULED", "ACCESS_FAILED")


def _check_occ(wo, expected):
    if expected != wo["version"]:
        raise_err("ERR_STALE_WORK_ORDER_VERSION",
                  "expected_work_order_version does not match current version")


@bp.post("/api/work-orders")
@require_roles("Scheduler")
def create_work_order():
    b = body()
    wave_id = b.get("wave_id")
    wave = None
    if isinstance(wave_id, str):
        wave = get_or_404(db.waves, wave_id, "Wave")
    wave_id = req_str(b, "wave_id")
    if wave is None:
        wave = get_or_404(db.waves, wave_id, "Wave")
    account_id = b.get("service_account_id")
    account = None
    if isinstance(account_id, str):
        account = get_or_404(db.accounts, account_id, "ServiceAccount")
    account_id = req_str(b, "service_account_id")
    if account is None:
        account = get_or_404(db.accounts, account_id, "ServiceAccount")
    # State (stage 7): work orders are created in an OPEN wave (PRD 3.3).
    if wave["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Wave is not OPEN")
    # Program-active gate (stage 8).
    program = get_or_404(db.programs, wave["program_id"], "Program")
    if program["status"] != "ACTIVE":
        raise_err("ERR_PROGRAM_NOT_ACTIVE",
                  "Work order creation requires an ACTIVE program")
    # Wave capacity (stage 11): committed_count still below capacity.
    committed_count, _ = wave_counts(wave)
    if committed_count >= wave["capacity"]:
        raise_err("ERR_WAVE_CAPACITY_EXCEEDED", "Wave is at capacity")
    # One open work order per account (stage 11).
    for other in db.work_orders.values():
        if (
            other["service_account_id"] == account["id"]
            and other["lifecycle_status"] not in OPEN_WO_STATES
        ):
            raise_err("ERR_ACCOUNT_ALREADY_IN_PROGRAM",
                      "Account already has an open work order")
    old_meter_id = None
    for m in db.meters.values():
        if m["service_account_id"] == account["id"] and m["status"] == "INSTALLED":
            old_meter_id = m["id"]
            break
    wo = base_resource()
    wo.update({
        "wave_id": wave["id"],
        "service_account_id": account["id"],
        "contractor_id": None,
        "old_meter_id": old_meter_id,
        "new_meter_id": None,
        "committed_amount_cents": program["default_unit_allowance_cents"],
        "provisional_trueup_cents": None,
        "trueup_amount_cents": None,
        "trueup_delta_cents": None,
        "no_access_strikes": 0,
        "closed_at": None,
        "lifecycle_status": "CREATED",
        "hold_status": "CLEAR",
        "_swap_final_read_value": None,
    })
    db.work_orders[wo["id"]] = wo
    # System transition: account ELIGIBLE -> IN_PROGRAM (PRD 3.2).
    if account["status"] == "ELIGIBLE":
        account["status"] = "IN_PROGRAM"
        touch(account)
    return ok_object(ser_work_order(wo), 201)


@bp.get("/api/work-orders")
@require_roles(*ALL_ROLES)
def list_work_orders():
    filters = {}
    for k in ("wave_id", "service_account_id", "contractor_id", "old_meter_id",
              "new_meter_id"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    if request.args.get("status") is not None:
        filters["lifecycle_status"] = request.args["status"]
    return list_page(db.work_orders.values(), filters, ser_work_order)


@bp.get("/api/work-orders/<workOrderId>")
@require_roles(*ALL_ROLES)
def get_work_order(workOrderId):
    return ok_object(ser_work_order(get_or_404(db.work_orders, workOrderId, "WorkOrder")))


@bp.post("/api/work-orders/<workOrderId>/assign")
@require_roles("Scheduler")
def assign_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, "WorkOrder")
    b = body()
    contractor_id = b.get("contractor_id")
    contractor = None
    if isinstance(contractor_id, str):
        contractor = get_or_404(db.contractors, contractor_id, "Contractor")
    contractor_id = req_str(b, "contractor_id")
    if contractor is None:
        contractor = get_or_404(db.contractors, contractor_id, "Contractor")
    expected_version = req_int(b, "expected_work_order_version")
    if wo["lifecycle_status"] not in ASSIGNABLE_STATES:
        raise_err("ERR_INVALID_STATE",
                  "Work order cannot be assigned from its current state")
    _check_occ(wo, expected_version)
    if contractor["status"] != "ACTIVE":
        raise_err("ERR_CONTRACTOR_NOT_ACTIVE", "Contractor is not ACTIVE")
    wave = get_or_404(db.waves, wo["wave_id"], "Wave")
    if contractor["program_id"] != wave["program_id"]:
        raise_err("ERR_CROSS_PROGRAM_REFERENCE",
                  "Contractor belongs to a different program")
    wo["contractor_id"] = contractor["id"]
    # Each assignment reprices the commitment to the contractor's unit price.
    wo["committed_amount_cents"] = contractor["unit_price_cents"]
    touch(wo)
    return ok_object(ser_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/swap")
@require_roles("FieldContractor")
def swap_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, "WorkOrder")
    check_contractor_ownership(wo["contractor_id"])
    b = body()
    new_meter_id = b.get("new_meter_id")
    new_meter = None
    if isinstance(new_meter_id, str):
        new_meter = get_or_404(db.meters, new_meter_id, "Meter")
    new_meter_id = req_str(b, "new_meter_id")
    if new_meter is None:
        new_meter = get_or_404(db.meters, new_meter_id, "Meter")
    final_read = req_int(b, "final_read_value", min=0)
    initial_read = req_int(b, "initial_read_value", min=0)
    expected_version = req_int(b, "expected_work_order_version")
    # State (stage 7).
    if wo["lifecycle_status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Work order is not SCHEDULED")
    if wo["hold_status"] != "CLEAR":
        raise_err("ERR_INVALID_STATE", "Work order is ON_HOLD")
    if not any(
        a["work_order_id"] == wo["id"] and a["status"] == "COMPLETED"
        for a in db.appointments.values()
    ):
        raise_err("ERR_INVALID_STATE",
                  "Work order has no COMPLETED appointment")
    # OCC (precondition order per swap state machine).
    _check_occ(wo, expected_version)
    # Meter compatibility (stage 13).
    if new_meter["status"] != "IN_STOCK" or new_meter["technology"] != "AMI":
        raise_err("ERR_METER_NOT_AVAILABLE",
                  "New meter must be IN_STOCK and AMI")
    account = get_or_404(db.accounts, wo["service_account_id"], "ServiceAccount")
    # Reading plausibility (stage 13).
    if final_read < account["last_billed_read_value"]:
        raise_err("ERR_READING_SEQUENCE_INVALID",
                  "final_read_value below last billed read")
    if initial_read > FACTORY_INITIAL_READ_MAX_CCF:
        raise_err("ERR_READING_SEQUENCE_INVALID",
                  "initial_read_value exceeds factory ceiling")
    program = get_or_404(
        db.programs, get_or_404(db.waves, wo["wave_id"], "Wave")["program_id"],
        "Program")
    # Full cascade lands at once (PRD 3.5).
    if wo["old_meter_id"]:
        old_meter = db.meters.get(wo["old_meter_id"])
        if old_meter and old_meter["status"] == "INSTALLED":
            old_meter["status"] = "REMOVED"
            old_meter["service_account_id"] = None
            touch(old_meter)
    new_meter["status"] = "INSTALLED"
    new_meter["service_account_id"] = account["id"]
    new_meter["installed_read_value"] = initial_read
    touch(new_meter)
    wo["new_meter_id"] = new_meter["id"]
    wo["_swap_final_read_value"] = final_read
    wo["provisional_trueup_cents"] = swap_trueup_prorated(
        account, program, clock_now())
    if account["status"] == "IN_PROGRAM":
        account["status"] = "REPLACED"
        touch(account)
    wo["lifecycle_status"] = "SWAPPED"
    touch(wo)
    return ok_object(ser_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/reconcile")
@require_roles("FieldContractor")
def reconcile_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, "WorkOrder")
    check_contractor_ownership(wo["contractor_id"])
    b = body()
    expected_version = req_int(b, "expected_work_order_version")
    if wo["lifecycle_status"] != "SWAPPED":
        raise_err("ERR_INVALID_STATE", "Work order is not SWAPPED")
    _check_occ(wo, expected_version)
    has_final = any(
        r["work_order_id"] == wo["id"] and r["meter_id"] == wo["old_meter_id"]
        and r["read_type"] == "FINAL"
        for r in db.readings.values()
    )
    has_initial = any(
        r["work_order_id"] == wo["id"] and r["meter_id"] == wo["new_meter_id"]
        and r["read_type"] == "INITIAL"
        for r in db.readings.values()
    )
    if not (has_final and has_initial):
        raise_err("ERR_RECONCILE_READINGS_INCOMPLETE",
                  "FINAL (old meter) and INITIAL (new meter) readings required")
    account = get_or_404(db.accounts, wo["service_account_id"], "ServiceAccount")
    program = get_or_404(
        db.programs, get_or_404(db.waves, wo["wave_id"], "Wave")["program_id"],
        "Program")
    measured = swap_trueup_measured(wo["_swap_final_read_value"], account, program)
    wo["trueup_amount_cents"] = measured
    wo["trueup_delta_cents"] = measured - wo["provisional_trueup_cents"]
    wo["lifecycle_status"] = "RECONCILED"
    touch(wo)
    return ok_object(ser_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/submit-rework")
@require_roles("FieldContractor")
def submit_rework(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, "WorkOrder")
    check_contractor_ownership(wo["contractor_id"])
    b = body()
    expected_version = req_int(b, "expected_work_order_version")
    if wo["lifecycle_status"] != "QA_FAILED":
        raise_err("ERR_INVALID_STATE", "Work order is not QA_FAILED")
    _check_occ(wo, expected_version)
    wo["lifecycle_status"] = "QA_REVIEW"
    touch(wo)
    return ok_object(ser_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/close")
@require_roles("Scheduler")
def close_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, "WorkOrder")
    if wo["lifecycle_status"] != "QA_REVIEW":
        raise_err("ERR_INVALID_STATE", "Work order is not QA_REVIEW")
    if wo["hold_status"] != "CLEAR":
        raise_err("ERR_INVALID_STATE", "Work order is ON_HOLD")
    for a in db.quality_audits.values():
        if a["work_order_id"] == wo["id"] and a["result_status"] == "PENDING":
            raise_err("ERR_INVALID_STATE",
                      "Work order has a PENDING quality audit")
    for c in db.complaints.values():
        if c["work_order_id"] == wo["id"] and c["status"] in OPEN_COMPLAINT_STATES:
            raise_err("ERR_OPEN_COMPLAINT_EXISTS",
                      "Work order has an open complaint")
    for case in db.no_access_cases.values():
        if case["work_order_id"] == wo["id"] and case["status"] == "OPEN":
            raise_err("ERR_OPEN_NO_ACCESS_CASE",
                      "Work order has an OPEN no-access case")
    wo["lifecycle_status"] = "CLOSED"
    wo["closed_at"] = clock_now()
    wo["committed_amount_cents"] = 0
    touch(wo)
    return ok_object(ser_work_order(wo))


@bp.post("/api/work-orders/<workOrderId>/cancel")
@require_roles("Scheduler")
def cancel_work_order(workOrderId):
    wo = get_or_404(db.work_orders, workOrderId, "WorkOrder")
    if wo["lifecycle_status"] not in ASSIGNABLE_STATES:
        raise_err("ERR_INVALID_STATE",
                  "Work order cannot be cancelled from its current state")
    for case in db.no_access_cases.values():
        if case["work_order_id"] == wo["id"] and case["status"] == "OPEN":
            raise_err("ERR_OPEN_NO_ACCESS_CASE",
                      "Work order has an OPEN no-access case")
    account = db.accounts.get(wo["service_account_id"])
    wo_cancel_cascade(wo)
    if account is not None:
        account_return_to_eligible_if_clear(account, exclude_wo_id=wo["id"])
    return ok_object(ser_work_order(wo))
