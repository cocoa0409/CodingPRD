"""Regulatory filings and late-filing assessments (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import COMPLIANCE_MANAGER, REGULATOR, endpoint, read_endpoint
from services import guards, reports

bp = Blueprint("regulatory_reports", __name__)

ZERO_2 = Decimal("0.00")


@bp.post("/regulatory-reports")
@endpoint([COMPLIANCE_MANAGER])
def create_report():
    payload = validate.body()
    store_id = validate.req_id(payload, "store_id")
    report_type = validate.req_enum(payload, "report_type", constants.REPORT_TYPES)
    period_start = validate.req_instant(payload, "period_start")
    period_end = validate.req_instant(payload, "period_end")
    leaked_lbs_method = validate.req_enum(payload, "leaked_lbs_method",
                                         constants.LEAKED_LBS_METHODS)
    if period_end <= period_start:
        raise invalid("period_end must be strictly later than period_start")
    db.require("stores", store_id)
    guards.require_not_after_clock(period_end)
    if reports.overlapping_report(store_id, period_start, period_end) is not None:
        raise ApiError("ERR_REPORT_PERIOD_OVERLAP")

    report = db.new_entity()
    report.update({
        "store_id": store_id,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "leaked_lbs_method": leaked_lbs_method,
        "total_leaked_lbs": util.q1(Decimal("0")),
        "included_system_count": 0,
        "due_on": util.add_days(period_end, constants.REPORT_DUE_DAYS),
        "status": "DRAFT",
        "submission_count": 0,
        "submitted_at": None,
        "submission_note": None,
        "decided_at": None,
        "days_late": 0,
        "base_assessment_usd": ZERO_2,
        "administrative_surcharge_usd": ZERO_2,
        "late_filing_assessment_usd": ZERO_2,
        "rejection_reason_code": None,
    })
    reports.recompute_totals(report)
    db.insert("regulatory_reports", report)
    return response.created(report)


@bp.get("/regulatory-reports")
@read_endpoint
def list_reports():
    filters = {
        "store_id": request.args.get("store_id"),
        "report_type": request.args.get("report_type"),
        "status": request.args.get("status"),
        "leaked_lbs_method": request.args.get("leaked_lbs_method"),
    }
    return response.listing(db.values("regulatory_reports"), filters)


@bp.get("/regulatory-reports/<report_id>")
@read_endpoint
def get_report(report_id):
    return response.ok(db.require("regulatory_reports", report_id))


@bp.post("/regulatory-reports/<report_id>/submission")
@endpoint([COMPLIANCE_MANAGER])
def submit_report(report_id):
    payload = validate.body()
    submission_note = validate.opt_str(payload, "submission_note")
    report = db.require("regulatory_reports", report_id)
    guards.require_state(report["status"] in ("DRAFT", "REJECTED"))
    clock = db.now()
    snap = db.snapshot(report)
    reports.recompute_totals(report)
    reports.assess_late_filing(report, clock)
    report["status"] = "SUBMITTED"
    report["submitted_at"] = clock
    report["submission_count"] = report["submission_count"] + 1
    if submission_note is not None:
        report["submission_note"] = submission_note
    db.commit(report, snap)
    return response.ok(report)


@bp.post("/regulatory-reports/<report_id>/decision")
@endpoint([REGULATOR])
def decide_report(report_id):
    payload = validate.body()
    decision = validate.req_enum(payload, "decision", ("ACCEPT", "REJECT"))
    rejection_reason_code = None
    if decision == "REJECT":
        rejection_reason_code = validate.req_str(payload, "rejection_reason_code")
    report = db.require("regulatory_reports", report_id)
    guards.require_state(report["status"] == "SUBMITTED")
    snap = db.snapshot(report)
    report["decided_at"] = db.now()
    if decision == "ACCEPT":
        report["status"] = "ACCEPTED"
        report["rejection_reason_code"] = None
    else:
        report["status"] = "REJECTED"
        report["rejection_reason_code"] = rejection_reason_code
    db.commit(report, snap)
    return response.ok(report)
