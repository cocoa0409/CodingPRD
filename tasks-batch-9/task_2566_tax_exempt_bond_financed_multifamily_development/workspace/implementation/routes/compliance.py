"""Annual compliance certifications, recapture and physical inspections (PRD 3.9)."""

from flask import Blueprint

import calc
import domain
import serialize
import validation as v
from auth import guard, own_project
from envelope import object_response
from errors import fail
from store import add_days, db, new_row, parse_iso, touch

bp = Blueprint("compliance", __name__)

BLOCKING_INSPECTION_STATUSES = ("SCHEDULED", "COMPLETED", "MISSED")
INSPECTION_BUFFER_DAYS = 14
INSPECTION_INTERVAL_DAYS = 1095
MIN_AMI_PERCENT = 1
MAX_AMI_PERCENT = 80


@bp.post("/compliance-reports")
def create_report():
    caller = guard("POST /compliance-reports")
    body = v.body()
    own_project(caller, domain.soft_get(db.projects, body.get("project_id")))

    project_id = v.req_id(body, "project_id")
    reporting_year = v.req_int(body, "reporting_year", minimum=1)
    restricted_units_occupied = v.req_int(body, "restricted_units_occupied", minimum=0)
    total_units_occupied = v.req_int(body, "total_units_occupied", minimum=0)
    average_ami_percent = v.req_int(body, "average_ami_percent", minimum=0)

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")
    own_project(caller, project)

    # Rule 20 (priority 103): one report per (project, year), inside the covenant span.
    for other in calc.project_reports(project_id):
        if other.get("reporting_year") == reporting_year:
            fail("ERR_DUPLICATE_COMPLIANCE_REPORT",
                 "A report already exists for reporting year %s." % reporting_year)
    start = parse_iso(project.get("compliance_start_date"))
    end = parse_iso(project.get("extended_use_end_date"))
    if start is None or end is None:
        fail("ERR_DUPLICATE_COMPLIANCE_REPORT",
             "The development has no compliance period to report against.")
    if reporting_year < start.year or reporting_year > end.year:
        fail("ERR_DUPLICATE_COMPLIANCE_REPORT",
             "reporting_year %s falls outside the covenant span %d-%d."
             % (reporting_year, start.year, end.year))

    # Rule 36 (priority 136): the count chain and the average-income band.
    total_units = project.get("total_units") or 0
    if (restricted_units_occupied > total_units_occupied
            or total_units_occupied > total_units):
        fail("ERR_REPORT_COUNTS_INCOHERENT",
             "restricted_units_occupied <= total_units_occupied <= total_units is "
             "required.")
    if not (MIN_AMI_PERCENT <= average_ami_percent <= MAX_AMI_PERCENT):
        fail("ERR_REPORT_COUNTS_INCOHERENT",
             "average_ami_percent must lie between %d and %d inclusive."
             % (MIN_AMI_PERCENT, MAX_AMI_PERCENT))

    achieved = calc.achieved_set_aside_bps(restricted_units_occupied, total_units)
    threshold = calc.required_set_aside_threshold_bps(project.get("set_aside_election"))
    shortfall = max(0, threshold - achieved)

    row = new_row(db.reports, {
        "project_id": project_id,
        "reporting_year": reporting_year,
        "restricted_units_occupied": restricted_units_occupied,
        "total_units_occupied": total_units_occupied,
        "average_ami_percent": average_ami_percent,
        "achieved_set_aside_bps": achieved,
        "shortfall_bps": shortfall,
        "status": "SUBMITTED",
        "finding_notes": None,
        "reviewed_by_user_id": None,
    })
    return object_response(serialize.report(row), 201)


@bp.post("/compliance-reports/<row_id>/review")
def review_report(row_id):
    caller = guard("POST /compliance-reports/{id}/review")
    body = v.body()
    finding = v.req_enum(body, "finding", ("CLEARED", "NONCOMPLIANCE"))
    finding_notes = v.opt_str(body, "finding_notes")

    report = domain.get_or_404(db.reports, row_id, "ERR_COMPLIANCE_REPORT_NOT_FOUND")
    if report.get("status") != "SUBMITTED":
        fail("ERR_COMPLIANCE_REPORT_STATE_INVALID",
             "A report in %s cannot be reviewed." % report.get("status"))

    shortfall = report.get("shortfall_bps") or 0
    if finding == "CLEARED" and shortfall != 0:
        fail("ERR_COMPLIANCE_REPORT_STATE_INVALID",
             "A report carrying a shortfall of %d bps cannot be cleared." % shortfall)
    if finding == "NONCOMPLIANCE" and shortfall == 0:
        fail("ERR_COMPLIANCE_REPORT_STATE_INVALID",
             "A report with no shortfall cannot carry a noncompliance finding.")

    project = domain.project_of_row(report)
    reporting_year = report.get("reporting_year") or 0

    if finding == "CLEARED":
        report["status"] = "CLEARED"
        report["finding_notes"] = finding_notes
        report["reviewed_by_user_id"] = caller.user_id
        touch(report)
        if project is not None:
            triggered_year = domain.triggering_report_year(project["id"])
            if triggered_year is not None and reporting_year > triggered_year:
                domain.cure_cascade(project)
        return object_response(serialize.report(report))

    report["status"] = "NONCOMPLIANCE_FOUND"
    report["finding_notes"] = finding_notes
    report["reviewed_by_user_id"] = caller.user_id
    touch(report)
    if project is not None:
        domain.noncompliance_cascade(project, shortfall)
    return object_response(serialize.report(report))


@bp.post("/physical-inspections")
def create_inspection():
    guard("POST /physical-inspections")
    body = v.body()
    project_id = v.req_id(body, "project_id")
    start_raw, start_dt = v.req_dt(body, "window_start")
    end_raw, end_dt = v.req_dt(body, "window_end")
    inspector_name = v.req_str(body, "inspector_name", allow_empty=False)
    if end_dt < start_dt:
        fail("ERR_INVALID_REQUEST", "window_end must be at or after window_start.")

    project = domain.get_or_404(db.projects, project_id, "ERR_PROJECT_NOT_FOUND")

    # Rule 18 (priority 101): closed windows plus a fourteen-day buffer on each side.
    buffered_start = add_days(start_dt, -INSPECTION_BUFFER_DAYS)
    buffered_end = add_days(end_dt, INSPECTION_BUFFER_DAYS)
    for other in calc.project_inspections(project_id):
        if other.get("status") not in BLOCKING_INSPECTION_STATUSES:
            continue
        other_start = parse_iso(other.get("window_start"))
        other_end = parse_iso(other.get("window_end"))
        if other_start is None or other_end is None:
            continue
        if buffered_start <= other_end and other_start <= buffered_end:
            fail("ERR_INSPECTION_WINDOW_CONFLICT",
                 "The window falls within fourteen days of an existing inspection.")

    # Rule 19 (priority 102): wholly inside the compliance period, bounds inclusive.
    period_start = parse_iso(project.get("compliance_start_date"))
    period_end = parse_iso(project.get("extended_use_end_date"))
    if period_start is None or period_end is None:
        fail("ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD",
             "The development has no compliance period yet.")
    if start_dt < period_start or end_dt > period_end:
        fail("ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD",
             "The window must lie inside the development's compliance period.")

    row = new_row(db.inspections, {
        "project_id": project_id,
        "window_start": start_raw,
        "window_end": end_raw,
        "inspector_name": inspector_name,
        "status": "SCHEDULED",
        "completed_date": None,
        "score": None,
        "deficiency_count": None,
        "next_inspection_due_date": None,
    })
    return object_response(serialize.inspection(row), 201)


@bp.post("/physical-inspections/<row_id>/complete")
def complete_inspection(row_id):
    guard("POST /physical-inspections/{id}/complete")
    body = v.body()
    completed_raw, completed_dt = v.req_dt(body, "completed_date")
    score = v.req_int(body, "score", minimum=0, maximum=100)
    deficiency_count = v.req_int(body, "deficiency_count", minimum=0)

    inspection = domain.get_or_404(db.inspections, row_id, "ERR_INSPECTION_NOT_FOUND")
    if inspection.get("status") != "SCHEDULED":
        fail("ERR_INSPECTION_STATE_INVALID",
             "An inspection in %s cannot be completed." % inspection.get("status"))

    window_start = parse_iso(inspection.get("window_start"))
    window_end = parse_iso(inspection.get("window_end"))
    if window_start is not None and completed_dt < window_start:
        fail("ERR_INVALID_REQUEST", "completed_date precedes the scheduled window.")
    if window_end is not None and completed_dt > window_end:
        fail("ERR_INVALID_REQUEST", "completed_date falls after the scheduled window.")

    inspection["status"] = "COMPLETED"
    inspection["completed_date"] = completed_raw
    inspection["score"] = score
    inspection["deficiency_count"] = deficiency_count
    inspection["next_inspection_due_date"] = domain.plus_days(
        completed_raw, INSPECTION_INTERVAL_DAYS)
    touch(inspection)
    return object_response(serialize.inspection(inspection))
