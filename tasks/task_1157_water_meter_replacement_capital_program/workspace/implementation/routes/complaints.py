"""High-bill complaint endpoints (PRD 3.8): filing, triage, bench-test order,
adjudication with the two adjustment variants, withdrawal."""
import db
from db import base_resource, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import (
    MANDATORY_BENCH_VARIANCE_PCT,
    OPEN_COMPLAINT_STATES,
    complaint_adjustment,
    complaint_variance_pct,
    get_or_404,
    linked_fail_bench_test_exists,
    list_page,
    maybe_release_hold,
    ser_complaint,
)
from flask import Blueprint, request
from validate import body, req_dt, req_enum, req_int, req_str

bp = Blueprint("complaints", __name__)

SWAPPED_OR_LATER = (
    "SWAPPED", "RECONCILED", "AMI_VERIFIED", "QA_REVIEW", "QA_FAILED", "CLOSED",
)
DECISIONS = ("ADJUSTED", "DENIED")
WITHDRAWABLE = ("FILED", "UNDER_REVIEW", "BENCH_TEST_ORDERED")


@bp.post("/api/complaints")
@require_roles("CustomerService")
def file_complaint():
    b = body()
    account_id = b.get("service_account_id")
    if isinstance(account_id, str):
        get_or_404(db.accounts, account_id, "ServiceAccount")
    account_id = req_str(b, "service_account_id")
    account = get_or_404(db.accounts, account_id, "ServiceAccount")
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = req_str(b, "work_order_id")
    wo = get_or_404(db.work_orders, work_order_id, "WorkOrder")
    claimed = req_int(b, "claimed_bill_cents", min=0)
    baseline = req_int(b, "baseline_bill_cents", min=1)
    period_start = req_dt(b, "billing_period_start")
    period_end = req_dt(b, "billing_period_end")
    # State (stage 7): work order must be SWAPPED or later in its lifecycle.
    if wo["lifecycle_status"] not in SWAPPED_OR_LATER:
        raise_err("ERR_INVALID_STATE",
                  "Work order must be SWAPPED or later to file a complaint")
    # Open-item blocker (stage 12): one open complaint per work order.
    for c in db.complaints.values():
        if c["work_order_id"] == wo["id"] and c["status"] in OPEN_COMPLAINT_STATES:
            raise_err("ERR_OPEN_COMPLAINT_EXISTS",
                      "Work order already has an open complaint")
    # Referential (stage 13): the complaint's account is the work order's.
    if account["id"] != wo["service_account_id"]:
        raise_err("ERR_ACCOUNT_WORK_ORDER_MISMATCH",
                  "Complaint account does not match the work order's account")
    # Fiscal (stage 14): variance must be at least 25 percent.
    variance = complaint_variance_pct(claimed, baseline)
    if variance < 25:
        raise_err("ERR_COMPLAINT_VARIANCE_BELOW_THRESHOLD",
                  "variance_pct is below 25")
    c = base_resource()
    c.update({
        "service_account_id": account["id"],
        "work_order_id": wo["id"],
        "claimed_bill_cents": claimed,
        "baseline_bill_cents": baseline,
        "billing_period_start": period_start,
        "billing_period_end": period_end,
        "variance_pct": variance,
        "bench_test_id": None,
        "adjustment_cents": None,
        "adjudication_variant": None,
        "status": "FILED",
    })
    db.complaints[c["id"]] = c
    # Parallel hold dimension: CLEAR -> ON_HOLD on filing (PRD 3.8).
    if wo["hold_status"] == "CLEAR":
        wo["hold_status"] = "ON_HOLD"
        touch(wo)
    return ok_object(ser_complaint(c), 201)


@bp.get("/api/complaints")
@require_roles(*ALL_ROLES)
def list_complaints():
    filters = {}
    for k in ("service_account_id", "work_order_id", "bench_test_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.complaints.values(), filters, ser_complaint)


@bp.get("/api/complaints/<complaintId>")
@require_roles(*ALL_ROLES)
def get_complaint(complaintId):
    return ok_object(ser_complaint(
        get_or_404(db.complaints, complaintId, "HighBillComplaint")))


@bp.post("/api/complaints/<complaintId>/triage")
@require_roles("CustomerService")
def triage_complaint(complaintId):
    c = get_or_404(db.complaints, complaintId, "HighBillComplaint")
    if c["status"] != "FILED":
        raise_err("ERR_INVALID_STATE", "Complaint is not FILED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/api/complaints/<complaintId>/order-bench-test")
@require_roles("CustomerService")
def order_bench_test(complaintId):
    c = get_or_404(db.complaints, complaintId, "HighBillComplaint")
    if c["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    wo = get_or_404(db.work_orders, c["work_order_id"], "WorkOrder")
    old_meter = db.meters.get(wo["old_meter_id"]) if wo["old_meter_id"] else None
    if old_meter is None or old_meter["status"] != "REMOVED":
        raise_err("ERR_METER_NOT_AVAILABLE",
                  "The work order's old meter is not REMOVED")
    c["status"] = "BENCH_TEST_ORDERED"
    touch(c)
    return ok_object(ser_complaint(c))


@bp.post("/api/complaints/<complaintId>/adjudicate")
@require_roles("CustomerService")
def adjudicate_complaint(complaintId):
    c = get_or_404(db.complaints, complaintId, "HighBillComplaint")
    b = body()
    decision = req_enum(b, "decision", DECISIONS)
    if c["status"] != "UNDER_REVIEW":
        raise_err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    if decision == "ADJUSTED":
        # Safety (stage 9): variance >= 50 requires a linked FAIL bench test.
        if (c["variance_pct"] >= MANDATORY_BENCH_VARIANCE_PCT
                and not linked_fail_bench_test_exists(c)):
            raise_err("ERR_BENCH_TEST_REQUIRED",
                      "ADJUSTED with variance_pct >= 50 requires a linked FAIL bench test")
        adjustment, variant = complaint_adjustment(c)
        c["adjustment_cents"] = adjustment
        c["adjudication_variant"] = variant
        c["status"] = "ADJUSTED"
    else:
        c["status"] = "DENIED"
    touch(c)
    wo = db.work_orders.get(c["work_order_id"])
    if wo is not None:
        maybe_release_hold(wo)
    return ok_object(ser_complaint(c))


@bp.post("/api/complaints/<complaintId>/withdraw")
@require_roles("CustomerService")
def withdraw_complaint(complaintId):
    c = get_or_404(db.complaints, complaintId, "HighBillComplaint")
    if c["status"] not in WITHDRAWABLE:
        raise_err("ERR_INVALID_STATE",
                  "Complaint cannot be withdrawn from its current state")
    c["status"] = "WITHDRAWN"
    touch(c)
    wo = db.work_orders.get(c["work_order_id"])
    if wo is not None:
        maybe_release_hold(wo)
    return ok_object(ser_complaint(c))
