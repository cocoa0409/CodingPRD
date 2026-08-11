"""Bench test endpoints (PRD 3.8): synchronous accuracy computation, meter
verdict cascade, complaint link-back."""
import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import (
    bench_weighted_accuracy,
    get_or_404,
    list_page,
    ser_bench_test,
)
from flask import Blueprint, request
from validate import body, opt_str, req_number, req_str

bp = Blueprint("bench_tests", __name__)


@bp.post("/api/bench-tests")
@require_roles("QualityAuditor")
def create_bench_test():
    b = body()
    meter_id = b.get("meter_id")
    if isinstance(meter_id, str):
        get_or_404(db.meters, meter_id, "Meter")
    meter_id = req_str(b, "meter_id")
    meter = get_or_404(db.meters, meter_id, "Meter")
    work_order_id = b.get("work_order_id")
    if isinstance(work_order_id, str):
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    work_order_id = opt_str(b, "work_order_id")
    if work_order_id is not None:
        get_or_404(db.work_orders, work_order_id, "WorkOrder")
    complaint_id = b.get("complaint_id")
    if isinstance(complaint_id, str):
        get_or_404(db.complaints, complaint_id, "HighBillComplaint")
    complaint_id = opt_str(b, "complaint_id")
    if complaint_id is not None:
        get_or_404(db.complaints, complaint_id, "HighBillComplaint")
    measured_low = req_number(b, "measured_low_ccf", min=0)
    measured_mid = req_number(b, "measured_mid_ccf", min=0)
    measured_high = req_number(b, "measured_high_ccf", min=0)
    # Referential (stage 13): the meter must be REMOVED.
    if meter["status"] != "REMOVED":
        raise_err("ERR_METER_NOT_AVAILABLE", "Meter is not REMOVED")
    acc_low, acc_mid, acc_high, weighted, result = bench_weighted_accuracy(
        measured_low, measured_mid, measured_high)
    bt = base_resource()
    bt.update({
        "meter_id": meter["id"],
        "work_order_id": work_order_id,
        "complaint_id": complaint_id,
        "measured_low_ccf": measured_low,
        "measured_mid_ccf": measured_mid,
        "measured_high_ccf": measured_high,
        "accuracy_low_pct": acc_low,
        "accuracy_mid_pct": acc_mid,
        "accuracy_high_pct": acc_high,
        "weighted_accuracy_pct": weighted,
        "result": result,
        "tested_at": clock_now(),
    })
    db.bench_tests[bt["id"]] = bt
    meter["status"] = "BENCH_PASSED" if result == "PASS" else "BENCH_FAILED"
    touch(meter)
    if complaint_id is not None:
        complaint = db.complaints.get(complaint_id)
        if complaint is not None:
            complaint["bench_test_id"] = bt["id"]
            if complaint["status"] == "BENCH_TEST_ORDERED":
                complaint["status"] = "UNDER_REVIEW"
            touch(complaint)
    return ok_object(ser_bench_test(bt), 201)


@bp.get("/api/bench-tests")
@require_roles(*ALL_ROLES)
def list_bench_tests():
    filters = {}
    for k in ("meter_id", "work_order_id", "complaint_id", "result"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.bench_tests.values(), filters, ser_bench_test)


@bp.get("/api/bench-tests/<benchTestId>")
@require_roles(*ALL_ROLES)
def get_bench_test(benchTestId):
    return ok_object(ser_bench_test(
        get_or_404(db.bench_tests, benchTestId, "BenchTest")))
