"""Compliance report endpoints."""
from flask import Blueprint

import clock
import db
from errors import raise_err
from middleware import route
from response import success_object
from serializers import ser_compliance_report
from services import core
from validation import get_body, req_string

bp = Blueprint("reports", __name__)

_CHAIN = (("compliance_report", "report_id", db.compliance_reports),)


def _snapshot(report, year):
    included = [e for e in db.enrollments.values()
                if e["academic_year_id"] == year["id"]
                and e["enrollment_status"] != "WITHDRAWN"]
    included = core.sorted_by_created(included)
    report["total_enrollments"] = len(included)
    report["compliant_count"] = sum(
        1 for e in included if e["compliance_standing"] == "GOOD_STANDING")
    report["noncompliant_enrollment_ids"] = [
        e["id"] for e in included if e["compliance_standing"] != "GOOD_STANDING"]


@bp.route("/academic-years/<year_id>/compliance-reports", methods=["POST"])
@route(["AcademicDirector"],
       parent_chain=(("academic_year", "year_id", db.academic_years),))
def create_report(year_id):
    get_body()
    year = db.academic_years[year_id]
    if year["status"] != "CLOSED":
        raise_err("ERR_REPORT_YEAR_NOT_CLOSED",
                  "Report generation requires the year to be CLOSED")
    for r in db.compliance_reports.values():
        if r["academic_year_id"] == year_id and r["status"] in (
                "DRAFT", "SUBMITTED", "REJECTED"):
            raise_err("ERR_REPORT_ALREADY_OPEN",
                      "Year already has a report in DRAFT, SUBMITTED, or REJECTED")
    rec = core.make_record({
        "academic_year_id": year_id,
        "status": "DRAFT",
        "generated_at": clock.now_iso(),
        "submitted_at": None,
        "late": None,
        "total_enrollments": 0,
        "compliant_count": 0,
        "noncompliant_enrollment_ids": [],
        "rejection_reason": None,
    })
    _snapshot(rec, year)
    db.compliance_reports[rec["id"]] = rec
    return success_object(ser_compliance_report(rec), status=201)


@bp.route("/compliance-reports/<report_id>", methods=["GET"])
@route(["Registrar", "AcademicDirector", "StateAuditor"], parent_chain=_CHAIN)
def get_report(report_id):
    return success_object(ser_compliance_report(db.compliance_reports[report_id]))


@bp.route("/compliance-reports/<report_id>/submit", methods=["POST"])
@route(["AcademicDirector"], parent_chain=_CHAIN)
def submit_report(report_id):
    rep = db.compliance_reports[report_id]
    if rep["status"] not in ("DRAFT", "REJECTED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only DRAFT or REJECTED reports may be submitted")
    year = db.academic_years.get(rep["academic_year_id"])
    now_iso = clock.now_iso()
    rep["status"] = "SUBMITTED"
    rep["submitted_at"] = now_iso
    rep["late"] = clock.now() > clock.parse(year["state_report_due_date"])
    # resubmission recomputes the snapshot from current state
    _snapshot(rep, year)
    core.touch(rep)
    return success_object(ser_compliance_report(rep))


@bp.route("/compliance-reports/<report_id>/accept", methods=["POST"])
@route(["StateAuditor"], parent_chain=_CHAIN)
def accept_report(report_id):
    rep = db.compliance_reports[report_id]
    if rep["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED reports may be accepted")
    rep["status"] = "ACCEPTED"
    core.touch(rep)
    year = db.academic_years.get(rep["academic_year_id"])
    if year is not None and year["status"] == "CLOSED":
        year["status"] = "REPORTED"
        core.touch(year)
    return success_object(ser_compliance_report(rep))


@bp.route("/compliance-reports/<report_id>/reject", methods=["POST"])
@route(["StateAuditor"], parent_chain=_CHAIN)
def reject_report(report_id):
    rep = db.compliance_reports[report_id]
    body = get_body()
    reason = req_string(body, "reason")
    if rep["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED reports may be rejected")
    rep["status"] = "REJECTED"
    rep["rejection_reason"] = reason
    core.touch(rep)
    return success_object(ser_compliance_report(rep))
