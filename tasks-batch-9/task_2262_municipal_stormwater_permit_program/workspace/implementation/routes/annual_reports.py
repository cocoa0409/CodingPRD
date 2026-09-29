"""Annual reports: compilation, certification and submission."""

from datetime import timedelta

from flask import Blueprint

import middleware as mw
from db import DB, CLOCK, new_row, touch
from errors import ApiError
from middleware import body, get_date, get_int, get_str, require
from routes.common import find, one, require_active, settle
from services import calc, report

bp = Blueprint("annual_reports", __name__)

READERS = mw.OPERATIONAL_ROLES

ZERO_STATISTICS = {
    "screenings_completed": 0,
    "outfall_screening_coverage_pct": 0.00,
    "cases_opened": 0,
    "cases_resolved": 0,
    "construction_inspections_finalized": 0,
    "facility_inspections_finalized": 0,
    "enforcement_actions_issued": 0,
    "total_penalty_assessed_cents": 0,
    "swept_lane_miles": 0.00,
    "net_annual_load_lb": 0.00,
    "measurable_goals_met_count": 0,
    "compliance_index": 0.00,
}


@bp.post("/annual-reports")
def create_report():
    require([mw.MANAGER])
    payload = body()
    term_id = get_str(payload, "permit_term_id")
    start = get_date(payload, "reporting_period_start")
    end = get_date(payload, "reporting_period_end")
    if end < start:
        raise ApiError(
            "ERR_VALIDATION", "reporting_period_end must not precede reporting_period_start."
        )

    term = find("permit_terms", term_id)
    term_start = calc.date.fromisoformat(term["term_start_date"])
    term_end = calc.date.fromisoformat(term["term_end_date"])
    if start < term_start or end > term_end:
        raise ApiError("ERR_REPORT_WINDOW_OUTSIDE_TERM")

    fields = {
        "permit_term_id": term["id"],
        "reporting_period_start": start.isoformat(),
        "reporting_period_end": end.isoformat(),
        "status": "DRAFT",
        "compiled_at": None,
        "compiled_by_user_id": None,
        "certified_by_user_id": None,
        "certification_statement": None,
        "certified_at": None,
        "submitted_at": None,
        "invalidation_count": 0,
        "invalidated_reason": None,
    }
    fields.update(ZERO_STATISTICS)
    row = new_row(fields)
    DB.annual_reports[row["id"]] = row
    return one(row, 201)


@bp.get("/annual-reports/<report_id>")
def read_report(report_id):
    require(READERS)
    return one(find("annual_reports", report_id))


@bp.post("/annual-reports/<report_id>/compile")
def compile_report(report_id):
    user_id, _role = require([mw.MANAGER])
    payload = body()
    expected = get_int(payload, "expected_permit_term_version")
    row = find("annual_reports", report_id)
    term = DB.permit_terms.get(row["permit_term_id"])
    if term is None or int(term.get("version") or 0) != expected:
        raise ApiError("ERR_PERMIT_TERM_VERSION_CONFLICT")
    if row["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT")
    require_active(term)
    if report.pending_samples_in_window(term, row):
        raise ApiError("ERR_PENDING_SAMPLES_IN_WINDOW")

    stamp = CLOCK.stamp()
    row.update(report.statistics(term, row))
    row["status"] = "COMPILED"
    row["compiled_at"] = stamp
    row["compiled_by_user_id"] = user_id
    touch(row)
    term["last_compiled_at"] = stamp
    touch(term)
    settle(term)
    return one(row)


@bp.post("/annual-reports/<report_id>/certify")
def certify_report(report_id):
    user_id, _role = require([mw.MANAGER])
    payload = body()
    statement = get_str(payload, "certification_statement")
    row = find("annual_reports", report_id)
    if row["status"] != "COMPILED":
        raise ApiError("ERR_REPORT_NOT_COMPILED")
    if row.get("compiled_by_user_id") == user_id:
        raise ApiError("ERR_SAME_USER_CERTIFICATION")
    term = DB.permit_terms.get(row["permit_term_id"])
    if term is not None and term.get("compliance_posture") == "NON_COMPLIANT":
        raise ApiError("ERR_POSTURE_NON_COMPLIANT")

    row["status"] = "CERTIFIED"
    row["certified_at"] = CLOCK.stamp()
    row["certified_by_user_id"] = user_id
    row["certification_statement"] = statement
    touch(row)
    return one(row)


@bp.post("/annual-reports/<report_id>/submit")
def submit_report(report_id):
    require([mw.MANAGER])
    row = find("annual_reports", report_id)
    if row["status"] != "CERTIFIED":
        raise ApiError("ERR_REPORT_NOT_CERTIFIED")
    deadline = calc.date.fromisoformat(row["reporting_period_end"]) + timedelta(
        days=calc.SUBMISSION_WINDOW_DAYS
    )
    if CLOCK.now().date() > deadline:
        raise ApiError("ERR_REPORT_SUBMISSION_WINDOW_CLOSED")

    row["status"] = "SUBMITTED"
    row["submitted_at"] = CLOCK.stamp()
    touch(row)
    return one(row)
