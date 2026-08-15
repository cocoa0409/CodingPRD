"""Regulatory report endpoints (PRD §3.9).

Metrics are computed on demand into the DRAFT report; submission requires the
metrics to have been computed. Period bounds: end strictly after start and not
in the future (against the logical clock); period is [start, end).
"""

from __future__ import annotations

from flask import Blueprint

import db
from constants import REPORT_TYPES
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_REPORT_PERIOD_INVALID,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import pub_report
from util import (
    apply_filters,
    get_json_body,
    page_of,
    parse_pagination,
    path_or_404,
    require_enum,
    require_state_code,
    require_ts,
    require_string,
    sort_created,
)

bp = Blueprint("reports", __name__)

COMPLIANCE = ("SIUComplianceOfficer",)
READERS = ("SIUManager", "SIUComplianceOfficer")


def _in_period(parsed, start, end) -> bool:
    return parsed is not None and start <= parsed < end


@bp.post("/siu/reports")
@require_roles(*COMPLIANCE)
def create_report(_user_id: str, _role: str):
    body = get_json_body()
    period_start_at = require_ts(body, "period_start_at")
    period_end_at = require_ts(body, "period_end_at")
    state_code = require_state_code(body, "state_code")
    report_type = require_enum(body, "report_type", REPORT_TYPES)
    start = db.parse_instant(period_start_at)
    end = db.parse_instant(period_end_at)
    if end <= start or end > db.clock.now:
        raise_err(
            ERR_REPORT_PERIOD_INVALID,
            "period_end_at must be after period_start_at and not in the future",
        )
    report = {
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "state_code": state_code,
        "report_type": report_type,
        "total_cases_opened": 0,
        "total_cases_closed_substantiated": 0,
        "total_restitution_recovered_cents": 0,
        "late_bureau_filings": 0,
        "status": "DRAFT",
        "_computed": False,
    }
    db.stamp_new(report)
    db.reports[report["id"]] = report
    return success_object(pub_report(report), 201)


@bp.get("/siu/reports/<reportId>")
@require_roles(*READERS)
def get_report(reportId: str, _user_id: str, _role: str):
    report = path_or_404(db.reports, reportId, "RegulatoryReport")
    return success_object(pub_report(report))


@bp.get("/siu/reports")
@require_roles(*READERS)
def list_reports(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = apply_filters(list(db.reports.values()), ["status", "state_code", "report_type"])
    items = sort_created(items)
    page, total = page_of(items, limit, offset)
    return success_list([pub_report(r) for r in page], limit, offset, total)


@bp.post("/siu/reports/<reportId>/compute")
@require_roles(*COMPLIANCE)
def compute_report(reportId: str, _user_id: str, _role: str):
    get_json_body()
    report = path_or_404(db.reports, reportId, "RegulatoryReport")
    if report.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Report must be DRAFT to compute metrics")
    start = db.parse_instant(report.get("period_start_at"))
    end = db.parse_instant(report.get("period_end_at"))
    state_code = report.get("state_code")

    opened = 0
    closed_substantiated = 0
    for case in db.cases.values():
        claim = db.claims.get(case.get("claim_id")) or {}
        if claim.get("state_code") != state_code:
            continue
        if _in_period(db.parse_instant(case.get("created_at")), start, end):
            opened += 1
        if case.get("status") == "CLOSED_SUBSTANTIATED" and _in_period(
            db.parse_instant(case.get("updated_at")), start, end
        ):
            closed_substantiated += 1

    recovered = 0
    for payment in db.payments.values():
        if payment.get("status") != "CLEARED":
            continue
        if not _in_period(db.parse_instant(payment.get("received_at")), start, end):
            continue
        ledger = db.ledgers.get(payment.get("ledger_id")) or {}
        case = db.cases.get(ledger.get("case_id")) or {}
        claim = db.claims.get(case.get("claim_id")) or {}
        if claim.get("state_code") == state_code:
            recovered += int(payment.get("amount_cents", 0))

    late_filings = 0
    for referral in db.bureau_referrals.values():
        if not referral.get("late_filing"):
            continue
        if referral.get("state_code") != state_code:
            continue
        if _in_period(db.parse_instant(referral.get("filed_at")), start, end):
            late_filings += 1

    report["total_cases_opened"] = opened
    report["total_cases_closed_substantiated"] = closed_substantiated
    report["total_restitution_recovered_cents"] = recovered
    report["late_bureau_filings"] = late_filings
    report["_computed"] = True
    db.touch(report)
    return success_object(pub_report(report))


@bp.post("/siu/reports/<reportId>/submit")
@require_roles(*COMPLIANCE)
def submit_report(reportId: str, _user_id: str, _role: str):
    get_json_body()
    report = path_or_404(db.reports, reportId, "RegulatoryReport")
    if report.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Report must be DRAFT to be submitted")
    if not report.get("_computed"):
        raise_err(ERR_INVALID_STATE, "Report metrics must be computed before submission")
    report["status"] = "SUBMITTED"
    db.touch(report)
    return success_object(pub_report(report))


@bp.post("/siu/reports/<reportId>/accept")
@require_roles(*COMPLIANCE)
def accept_report(reportId: str, _user_id: str, _role: str):
    get_json_body()
    report = path_or_404(db.reports, reportId, "RegulatoryReport")
    if report.get("status") != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Report must be SUBMITTED to be accepted")
    report["status"] = "ACCEPTED"
    db.touch(report)
    return success_object(pub_report(report))


@bp.post("/siu/reports/<reportId>/reject")
@require_roles(*COMPLIANCE)
def reject_report(reportId: str, _user_id: str, _role: str):
    body = get_json_body()
    require_string(body, "reason")
    report = path_or_404(db.reports, reportId, "RegulatoryReport")
    if report.get("status") != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Report must be SUBMITTED to be rejected")
    report["status"] = "REJECTED_BY_REGULATOR"
    db.touch(report)
    return success_object(pub_report(report))
