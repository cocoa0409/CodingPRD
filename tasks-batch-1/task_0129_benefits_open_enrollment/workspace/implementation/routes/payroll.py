"""Payroll run + DeductionLine + CarrierFeedRecord read endpoints (PRD §3.7, §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize,
    BENEFITS_ADMIN, PAYROLL_OFFICER, COMPLIANCE_OFFICER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("payroll", __name__)


# ---------------------------------------------------------------------------
# Payroll run (test-driving): advance one pay period.
# ---------------------------------------------------------------------------
@bp.route("/_payroll/run", methods=["POST"])
def payroll_run():
    role = authenticate()
    authorize(role, {PAYROLL_OFFICER})
    body = C.get_body()
    C.require_fields(body, ["employee_id"])
    employee_id = body["employee_id"]
    if not C.is_str(employee_id):
        raise E.invalid_request("employee_id must be a string")
    emp = get_or_404(db.employees, employee_id, "Employee")

    # The pay period this run bills is the current pay_periods_processed (0-based
    # index), then the counter advances.
    pay_period_index = emp["pay_periods_processed"]

    # One REGULAR DeductionLine per ACTIVE enrollment.
    active = [
        e for e in db.enrollments.values()
        if e["employee_id"] == employee_id and e["status"] == "ACTIVE"
    ]
    active = C.order_by_created(active)
    for enr in active:
        D.post_regular_deduction(enr, emp, pay_period_index)

    emp["pay_periods_processed"] = pay_period_index + 1
    C.touch(emp)
    return response.ok_object(C.serialize(emp), 200)


# ---------------------------------------------------------------------------
# DeductionLine reads
# ---------------------------------------------------------------------------
@bp.route("/deduction-lines/<line_id>", methods=["GET"])
def get_deduction_line(line_id):
    role = authenticate()
    authorize(role, {PAYROLL_OFFICER, BENEFITS_ADMIN, COMPLIANCE_OFFICER})
    line = get_or_404(db.deduction_lines, line_id, "DeductionLine")
    return response.ok_object(C.serialize(line), 200)


@bp.route("/deduction-lines", methods=["GET"])
def list_deduction_lines():
    role = authenticate()
    authorize(role, {PAYROLL_OFFICER, BENEFITS_ADMIN, COMPLIANCE_OFFICER})
    limit, offset = C.parse_pagination()
    args = request.args
    items = list(db.deduction_lines.values())
    for key in ("enrollment_id", "employee_id", "line_type"):
        val = args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# CarrierFeedRecord reads
# ---------------------------------------------------------------------------
@bp.route("/carrier-feed-records/<rec_id>", methods=["GET"])
def get_carrier_feed_record(rec_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN, COMPLIANCE_OFFICER, PAYROLL_OFFICER})
    rec = get_or_404(db.carrier_feed_records, rec_id, "CarrierFeedRecord")
    return response.ok_object(C.serialize(rec), 200)


@bp.route("/carrier-feed-records", methods=["GET"])
def list_carrier_feed_records():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN, COMPLIANCE_OFFICER, PAYROLL_OFFICER})
    limit, offset = C.parse_pagination()
    args = request.args
    items = list(db.carrier_feed_records.values())
    for key in ("enrollment_id", "transaction_set"):
        val = args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)
