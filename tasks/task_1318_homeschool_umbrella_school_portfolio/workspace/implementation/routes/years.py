"""Academic year endpoints."""
from datetime import date as _date

from flask import Blueprint, request

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object, success_list
from serializers import (
    ser_academic_year, ser_enrollment, ser_exam_session, ser_coop_class,
    ser_compliance_report,
)
from services import core
from services import compliance as compliance_svc
from validation import (
    get_body, req_string, req_date, req_datetime, opt_int_list, opt_int,
)

bp = Blueprint("years", __name__)


def _parse_date(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return _date(y, m, dd)


def _start_of_day(d):
    from datetime import datetime, timezone
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


@bp.route("/academic-years", methods=["POST"])
@route(["AcademicDirector"])
def create_year():
    body = get_body()
    label = req_string(body, "label")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    if _parse_date(end_date) < _parse_date(start_date):
        raise_err("ERR_INVALID_REQUEST", "end_date must be >= start_date")
    notice_filing_deadline = req_datetime(body, "notice_filing_deadline")
    portfolio_due_date = req_datetime(body, "portfolio_due_date")
    state_report_due_date = req_datetime(body, "state_report_due_date")
    mid_year_date = req_date(body, "mid_year_date")
    testing_grades = opt_int_list(body, "testing_grades", default=[3, 5, 8, 11], lo=0, hi=12)
    required_instructional_days = opt_int(body, "required_instructional_days", default=180, lo=0)
    required_minutes_elementary = opt_int(body, "required_minutes_elementary", default=54000, lo=0)
    required_minutes_secondary = opt_int(body, "required_minutes_secondary", default=59400, lo=0)

    for y in db.academic_years.values():
        if y["label"] == label:
            raise_err("ERR_INVALID_REQUEST", "label must be unique across all years")

    rec = core.make_record({
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "notice_filing_deadline": notice_filing_deadline,
        "portfolio_due_date": portfolio_due_date,
        "state_report_due_date": state_report_due_date,
        "mid_year_date": mid_year_date,
        "testing_grades": testing_grades,
        "required_instructional_days": required_instructional_days,
        "required_minutes_elementary": required_minutes_elementary,
        "required_minutes_secondary": required_minutes_secondary,
        "status": "PLANNING",
    })
    db.academic_years[rec["id"]] = rec
    return success_object(ser_academic_year(rec), status=201)


@bp.route("/academic-years/<year_id>", methods=["GET"])
@route(ALL_ROLES, parent_chain=(("academic_year", "year_id", db.academic_years),))
def get_year(year_id):
    return success_object(ser_academic_year(db.academic_years[year_id]))


@bp.route("/academic-years/<year_id>/open", methods=["POST"])
@route(["AcademicDirector"], parent_chain=(("academic_year", "year_id", db.academic_years),))
def open_year(year_id):
    year = db.academic_years[year_id]
    if year["status"] != "PLANNING":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Year is not PLANNING")
    if clock.now() >= _start_of_day(_parse_date(year["end_date"])):
        raise_err("ERR_ACADEMIC_YEAR_NOT_OPEN",
                  "Logical clock must read before end_date to open the year")
    year["status"] = "OPEN"
    core.touch(year)
    return success_object(ser_academic_year(year))


@bp.route("/academic-years/<year_id>/close", methods=["POST"])
@route(["AcademicDirector"], parent_chain=(("academic_year", "year_id", db.academic_years),))
def close_year(year_id):
    year = db.academic_years[year_id]
    if year["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Year is not OPEN")
    if clock.now() < _start_of_day(_parse_date(year["end_date"])):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Logical clock must be at or past end_date to close the year")
    year["status"] = "CLOSED"
    core.touch(year)
    return success_object(ser_academic_year(year))


@bp.route("/academic-years/<year_id>/run-compliance-sweep", methods=["POST"])
@route(["AcademicDirector"], parent_chain=(("academic_year", "year_id", db.academic_years),))
def sweep_year(year_id):
    year = db.academic_years[year_id]
    compliance_svc.run_sweep(year)
    return success_object(ser_academic_year(year))


@bp.route("/academic-years/<year_id>/enrollments", methods=["GET"])
@route(["Reviewer", "Registrar", "AcademicDirector", "StateAuditor"],
       parent_chain=(("academic_year", "year_id", db.academic_years),))
def list_year_enrollments(year_id):
    recs = [e for e in db.enrollments.values() if e["academic_year_id"] == year_id]
    status = request.args.get("enrollment_status")
    standing = request.args.get("compliance_standing")
    if status:
        recs = [e for e in recs if e["enrollment_status"] == status]
    if standing:
        recs = [e for e in recs if e["compliance_standing"] == standing]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_enrollment(e) for e in page], limit, offset, total)


@bp.route("/academic-years/<year_id>/exam-sessions", methods=["GET"])
@route(ALL_ROLES, parent_chain=(("academic_year", "year_id", db.academic_years),))
def list_year_exam_sessions(year_id):
    recs = [s for s in db.exam_sessions.values() if s["academic_year_id"] == year_id]
    status = request.args.get("status")
    if status:
        recs = [s for s in recs if s["status"] == status]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_exam_session(s) for s in page], limit, offset, total)


@bp.route("/academic-years/<year_id>/coop-classes", methods=["GET"])
@route(ALL_ROLES, parent_chain=(("academic_year", "year_id", db.academic_years),))
def list_year_coop_classes(year_id):
    recs = [c for c in db.coop_classes.values() if c["academic_year_id"] == year_id]
    status = request.args.get("status")
    if status:
        recs = [c for c in recs if c["status"] == status]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_coop_class(c) for c in page], limit, offset, total)


@bp.route("/academic-years/<year_id>/compliance-reports", methods=["GET"])
@route(["Registrar", "AcademicDirector", "StateAuditor"],
       parent_chain=(("academic_year", "year_id", db.academic_years),))
def list_year_reports(year_id):
    recs = [r for r in db.compliance_reports.values() if r["academic_year_id"] == year_id]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_compliance_report(r) for r in page], limit, offset, total)
