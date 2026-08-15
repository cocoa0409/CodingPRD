"""ComplianceReport endpoints: DRAFT -> SUBMITTED -> RETURNED/SUBMITTED ->
ACCEPTED revision loop with fill-rate computation."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_ALREADY_EXISTS,
    ERR_REPORT_INVALID_STATE,
    ERR_NO_SHIFTS_FOR_REPORT_DATE,
    ERR_SHIFTS_NOT_LOCKED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.core import compute_report_figures, pub
from util import get_json_body, req_iso_date, opt_str

bp = Blueprint("compliance_reports", __name__)


@bp.post("/compliance-reports")
@require_roles("NurseAdmin")
def create_compliance_report(_user_id: str, _role: str):
    body = get_json_body()
    report_date = req_iso_date(body, "report_date").isoformat()

    for r in db.reports.values():
        if r["report_date"] == report_date:
            raise_err(ERR_REPORT_ALREADY_EXISTS,
                      "A compliance report already exists for report_date")

    report = {
        "report_date": report_date,
        "status": "DRAFT",
        "return_reason": None,
        "shifts_included_count": None,
        "understaffed_shift_count": None,
        "fill_rate_shift_weighted_pct": None,
        "fill_rate_census_weighted_pct": None,
    }
    db.stamp_new(report)
    db.reports[report["id"]] = report
    return success_object(pub(report), 201)


@bp.get("/compliance-reports/<reportId>")
@require_roles(*ALL_ROLES)
def get_compliance_report(reportId: str, _user_id: str, _role: str):
    report = db.reports.get(reportId)
    if report is None:
        raise_err(ERR_REPORT_NOT_FOUND, "Compliance report not found")
    return success_object(pub(report))


@bp.post("/compliance-reports/<reportId>/submit")
@require_roles("NurseAdmin")
def submit_compliance_report(reportId: str, _user_id: str, _role: str):
    report = db.reports.get(reportId)
    if report is None:
        raise_err(ERR_REPORT_NOT_FOUND, "Compliance report not found")
    if report["status"] not in ("DRAFT", "RETURNED"):
        raise_err(ERR_REPORT_INVALID_STATE, "submit requires DRAFT or RETURNED")

    shifts_for_date = [
        s for s in db.shifts.values() if s["shift_date"] == report["report_date"]
    ]
    if not shifts_for_date:
        raise_err(ERR_NO_SHIFTS_FOR_REPORT_DATE,
                  "No shifts exist for the report_date")
    if any(s["status"] != "LOCKED" for s in shifts_for_date):
        raise_err(ERR_SHIFTS_NOT_LOCKED,
                  "Every shift for the report_date must be LOCKED")

    figures = compute_report_figures(report["report_date"])
    report.update(figures)
    report["status"] = "SUBMITTED"
    db.touch(report)
    return success_object(pub(report), 200)


@bp.post("/compliance-reports/<reportId>/return")
@require_roles("Regulator")
def return_compliance_report(reportId: str, _user_id: str, _role: str):
    report = db.reports.get(reportId)
    if report is None:
        raise_err(ERR_REPORT_NOT_FOUND, "Compliance report not found")
    if report["status"] != "SUBMITTED":
        raise_err(ERR_REPORT_INVALID_STATE, "return requires SUBMITTED")
    body = get_json_body()
    report["return_reason"] = opt_str(body, "return_reason", None)
    report["status"] = "RETURNED"
    db.touch(report)
    return success_object(pub(report), 200)


@bp.post("/compliance-reports/<reportId>/accept")
@require_roles("Regulator")
def accept_compliance_report(reportId: str, _user_id: str, _role: str):
    report = db.reports.get(reportId)
    if report is None:
        raise_err(ERR_REPORT_NOT_FOUND, "Compliance report not found")
    if report["status"] != "SUBMITTED":
        raise_err(ERR_REPORT_INVALID_STATE, "accept requires SUBMITTED")
    report["status"] = "ACCEPTED"
    db.touch(report)
    return success_object(pub(report), 200)
