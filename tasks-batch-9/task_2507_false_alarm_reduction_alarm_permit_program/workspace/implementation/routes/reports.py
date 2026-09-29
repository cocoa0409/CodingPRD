"""Compliance reports: filing, review, bounded correction and the company score."""

from flask import Blueprint

import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q,
                  q_instant, validate)
from errors import ApiError
from store import base_row, now, store, touch

bp = Blueprint("reports", __name__)

OPERATOR = ["AlarmCompanyOperator"]
REVIEW_ROLES = ["ProgramAdministrator", "FalseAlarmReviewOfficer"]
READ_ROLES = ["ProgramAdministrator", "FalseAlarmReviewOfficer", "PermitClerk",
              "AlarmCompanyOperator"]

LIVE_REPORT_STATUSES = ("SUBMITTED", "ACCEPTED", "VARIANCE_FLAGGED",
                        "CORRECTED")
VARIANCE_FLAG_FLOOR = 0.1000

CREATE_FIELDS = [
    F("monitoring_company_id", "uuid"),
    F("period_start", "ts"),
    F("period_end", "ts"),
    F("reported_dispatch_count", "int"),
    F("reported_cancellation_count", "int"),
    F("ecv_attempt_count", "int"),
]

REVIEW_FIELDS = [
    F("decision", "enum", values=("ACCEPT", "FLAG_VARIANCE")),
    F("variance_notes", "string", required=False),
]

CORRECT_FIELDS = [
    F("reported_dispatch_count", "int"),
    F("reported_cancellation_count", "int"),
    F("ecv_attempt_count", "int"),
]

METRIC_FIELDS = ("reported_dispatch_count", "reported_cancellation_count",
                 "ecv_attempt_count")


def _periods_overlap(new_start, new_end, old_start, old_end):
    """Closed intervals, zero buffer."""
    if old_start is None or old_end is None:
        return False
    return new_start <= old_end and old_start <= new_end


@bp.post("/compliance-reports")
def file_report():
    ctx = authenticate(OPERATOR)
    data = validate(ctx.body, CREATE_FIELDS)
    company = rt.resolve("AlarmCompany", data["monitoring_company_id"])
    check_owner(ctx, company_id=company["id"])
    period_start = data["period_start"]
    period_end = data["period_end"]
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "period_end must be strictly after period_start.")
    for report in engine.company_reports(company["id"]):
        if report.get("status") not in LIVE_REPORT_STATUSES:
            continue
        if _periods_overlap(period_start, period_end,
                            report.get("period_start"),
                            report.get("period_end")):
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP",
                           "This company already reported across that period.")

    row = base_row()
    row["monitoring_company_id"] = company["id"]
    row["period_start"] = period_start
    row["period_end"] = period_end
    row["reported_dispatch_count"] = data["reported_dispatch_count"]
    row["reported_cancellation_count"] = data["reported_cancellation_count"]
    row["ecv_attempt_count"] = data["ecv_attempt_count"]
    row["status"] = "SUBMITTED"
    row["correction_count"] = 0
    row["reviewed_at"] = None
    row["reviewed_by_user_id"] = None
    row["variance_notes"] = None
    engine.recompute_report_metrics(row)
    store.compliance_reports[row["id"]] = row
    engine.rollup_company(company)
    return created(row)


@bp.post("/compliance-reports/<report_id>/review")
def review_report(report_id):
    ctx = authenticate(REVIEW_ROLES)
    data = validate(ctx.body, REVIEW_FIELDS)
    report = rt.resolve("ComplianceReport", report_id)
    if report.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED report may be reviewed.")
    decision = data["decision"]
    if decision == "FLAG_VARIANCE" \
            and float(report.get("variance_pct") or 0) <= VARIANCE_FLAG_FLOOR:
        raise ApiError("ERR_NO_REPORTABLE_VARIANCE",
                       "The variance is not above the reportable floor.")
    report["reviewed_at"] = now()
    report["reviewed_by_user_id"] = ctx.user_id
    company = store.alarm_companies.get(report.get("monitoring_company_id"))
    if decision == "ACCEPT":
        report["status"] = "ACCEPTED"
        report["variance_notes"] = data.get("variance_notes")
        if company is not None:
            company["consecutive_flagged_report_count"] = 0
    else:
        report["status"] = "VARIANCE_FLAGGED"
        report["variance_notes"] = data.get("variance_notes")
        if company is not None:
            company["consecutive_flagged_report_count"] = (
                company.get("consecutive_flagged_report_count") or 0) + 1
    touch(report)
    if company is not None:
        engine.rollup_company(company, bump=False)
        engine.apply_company_status_from_score(
            company, "COMPLIANCE_SCORE_REVIEW")
        touch(company)
    return ok(report)


@bp.post("/compliance-reports/<report_id>/correct")
def correct_report(report_id):
    ctx = authenticate(OPERATOR)
    data = validate(ctx.body, CORRECT_FIELDS)
    report = rt.resolve("ComplianceReport", report_id)
    check_owner(ctx, company_id=report.get("monitoring_company_id"))
    if report.get("status") != "VARIANCE_FLAGGED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a VARIANCE_FLAGGED report may be corrected.")
    if all(data[field] == report.get(field) for field in METRIC_FIELDS):
        raise ApiError("ERR_NO_REPORTABLE_VARIANCE",
                       "A correction must change at least one reported metric.")
    if (report.get("correction_count") or 0) >= 2:
        raise ApiError("ERR_CORRECTION_LIMIT_REACHED",
                       "A report may be corrected at most twice.")
    for field in METRIC_FIELDS:
        report[field] = data[field]
    report["correction_count"] = (report.get("correction_count") or 0) + 1
    engine.recompute_report_metrics(report)
    # VARIANCE_FLAGGED -> CORRECTED -> SUBMITTED inside this one request.
    report["status"] = "CORRECTED"
    report["status"] = "SUBMITTED"
    report["reviewed_at"] = None
    report["reviewed_by_user_id"] = None
    report["variance_notes"] = None
    touch(report)
    company = store.alarm_companies.get(report.get("monitoring_company_id"))
    if company is not None:
        engine.rollup_company(company)
    return ok(report)


@bp.get("/compliance-reports/<report_id>")
def get_report(report_id):
    ctx = authenticate(READ_ROLES)
    report = rt.resolve("ComplianceReport", report_id)
    check_owner(ctx, company_id=report.get("monitoring_company_id"))
    return ok(report)


@bp.get("/compliance-reports")
def list_reports():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("ComplianceReport"), site_field=None)
    for field in ("monitoring_company_id", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    period_from = q_instant("period_from")
    period_to = q_instant("period_to")
    if period_from is not None:
        rows = [r for r in rows if r.get("period_start") is not None
                and r["period_start"] >= period_from]
    if period_to is not None:
        rows = [r for r in rows if r.get("period_start") is not None
                and r["period_start"] <= period_to]
    return listing(rows, rt.fields("ComplianceReport"))
