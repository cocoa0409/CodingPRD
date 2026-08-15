"""Annual monitoring reports (PRD §3.3)."""
from flask import Blueprint

import db
import errors
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    require_int,
    require_non_empty_string,
    require_number,
    require_roles,
)
from response import success_object
from routes.common import get_or_404, paginate
from services import calc, cascade

bp = Blueprint("monitoring", __name__)


def _check_score(name, value):
    if value < 0 or value > 100:
        raise_error(errors.ERR_INVALID_REQUEST, f"{name} must be within 0..100")


@bp.post("/authorizer/schools/<id>/monitoring-reports")
def create_report(id):
    user_id, _role = require_roles(["AuthorizerStaff"])
    school = get_or_404("schools", id)
    if school["status"] != "OPEN":
        raise_error(errors.ERR_SCHOOL_NOT_OPEN, "Monitoring reports require an OPEN school")
    data = body()
    fiscal_year = require_int(data, "fiscal_year")
    academic_score = require_number(data, "academic_score")
    financial_score = require_number(data, "financial_score")
    operational_score = require_number(data, "operational_score")
    _check_score("academic_score", academic_score)
    _check_score("financial_score", financial_score)
    _check_score("operational_score", operational_score)
    for r in db.all_records("monitoring_reports"):
        if r["school_id"] == id and r["fiscal_year"] == fiscal_year:
            raise_error(errors.ERR_DUPLICATE_RECORD, "Duplicate (school, fiscal_year) report")
    record = db.stamp_new({
        "school_id": id,
        "fiscal_year": fiscal_year,
        "academic_score": academic_score,
        "financial_score": financial_score,
        "operational_score": operational_score,
        "compliance_index": calc.compliance_index(academic_score, financial_score, operational_score),
        "submitted_by_user_id": user_id,
        "return_notes": None,
        "status": "SUBMITTED",
    })
    db.insert("monitoring_reports", record)
    return success_object(record, 201)


@bp.get("/authorizer/schools/<id>/monitoring-reports")
def list_reports(id):
    require_roles(ALL_ROLES)
    get_or_404("schools", id)
    records = [r for r in db.all_records("monitoring_reports") if r["school_id"] == id]
    return paginate(records)


@bp.post("/authorizer/monitoring-reports/<id>/submit")
def resubmit_report(id):
    require_roles(["AuthorizerStaff"])
    report = get_or_404("monitoring_reports", id)
    if report["status"] != "RETURNED":
        raise_error(errors.ERR_REPORT_INVALID_STATE, "Only a RETURNED report may be resubmitted")
    report["status"] = "SUBMITTED"
    report["return_notes"] = None
    report["compliance_index"] = calc.compliance_index(
        report["academic_score"], report["financial_score"], report["operational_score"]
    )
    db.touch(report)
    return success_object(report)


@bp.post("/authorizer/monitoring-reports/<id>/accept")
def accept_report(id):
    user_id, _role = require_roles(["AuthorizerStaff"])
    report = get_or_404("monitoring_reports", id)
    if report["status"] != "SUBMITTED":
        raise_error(errors.ERR_REPORT_INVALID_STATE, "Only a SUBMITTED report may be accepted")
    report["status"] = "ACCEPTED"
    db.touch(report)
    school = db.get("schools", report["school_id"])
    if school is not None:
        cascade.set_school_standings_from_report(school, report)
        cascade.auto_issue_probation_notices(school, report, user_id)
    return success_object(report)


@bp.post("/authorizer/monitoring-reports/<id>/return")
def return_report(id):
    require_roles(["AuthorizerStaff"])
    report = get_or_404("monitoring_reports", id)
    if report["status"] != "SUBMITTED":
        raise_error(errors.ERR_REPORT_INVALID_STATE, "Only a SUBMITTED report may be returned")
    data = body()
    notes = require_non_empty_string(data, "return_notes")
    report["status"] = "RETURNED"
    report["return_notes"] = notes
    db.touch(report)
    return success_object(report)
