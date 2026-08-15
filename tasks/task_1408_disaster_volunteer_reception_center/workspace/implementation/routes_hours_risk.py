"""HourEntry and RiskReport endpoints (cost-share ledger and risk pipeline)."""

from flask import Blueprint, g, request

import db
import services as svc
from errors import (
    ERR_DUPLICATE_HOUR_ENTRY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SOD_HOUR_VERIFICATION,
    ERR_SOD_RISK_ADJUDICATION,
    raise_error,
)
from middleware import ALL_ROLES, authenticate, authorize
from response import paginate, success_list, success_object
from validation import (
    RISK_CATEGORIES,
    SEVERITIES,
    check_hours_within_shift,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_enum,
    req_hours,
    req_string,
    utc_date_of,
)
from validators import (
    get_assignment_or_404,
    get_hour_entry_or_404,
    get_risk_report_or_404,
    incident_gate,
    load_fk_string,
)

bp = Blueprint("hours_risk", __name__)


# --- HourEntry ---------------------------------------------------------------------------

@bp.post("/vrc/hour-entries")
def create_hour_entry():
    authenticate()
    authorize(["Volunteer", "SiteSupervisor"])
    body = get_body()
    assignment_id = load_fk_string(body, "assignment_id", db.assignments, "DeploymentAssignment")
    check_unknown_fields(body, {"assignment_id", "work_date", "hours"})
    if not isinstance(assignment_id, str) or not assignment_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: assignment_id")
    work_date = body.get("work_date")
    if db.parse_date(work_date) is None:
        raise_error(ERR_INVALID_REQUEST, "Field work_date must be a YYYY-MM-DD calendar date")
    hours = req_hours(body, "hours")
    assignment = db.assignments[assignment_id]
    incident = db.incidents[assignment["incident_id"]]
    incident_gate(incident, "hour entry creation", demob_allowed=True)
    if assignment["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE, f"Assignment must be COMPLETED to report hours (current: {assignment['status']})")
    if g.role == "Volunteer" and g.user_id != assignment["volunteer_id"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only report hours on their own assignments")
    shift = db.shifts[assignment["site_shift_id"]]
    check_hours_within_shift(hours, shift)
    if work_date != utc_date_of(shift["start_at"]).isoformat():
        raise_error(ERR_INVALID_REQUEST, "work_date must equal the UTC calendar date of the shift's start_at")
    if any(e["assignment_id"] == assignment_id and e["work_date"] == work_date and e["status"] != "REJECTED_FINAL"
           for e in db.hour_entries.values()):
        raise_error(ERR_DUPLICATE_HOUR_ENTRY, "A live hour entry already exists for this assignment and work_date")
    rec = svc.create_record(db.hour_entries, {
        "assignment_id": assignment_id,
        "work_date": work_date,
        "hours": hours,
        "status": "SUBMITTED",
        "submitted_by_user_id": g.user_id,
        "verified_by_user_id": None,
        "dispute_count": 0,
        "resubmit_count": 0,
        "dispute_reason": None,
        "entry_value_cents": 0,
    })
    rec["entry_value_cents"] = svc.entry_value_cents(rec, assignment)
    return success_object(svc.hour_entry_view(rec), 201)


def _sod_hour_check(entry):
    if g.user_id == entry["submitted_by_user_id"]:
        raise_error(ERR_SOD_HOUR_VERIFICATION, "The submitter of an hour entry may not verify or dispute it")


@bp.post("/vrc/hour-entries/<entryId>/verify")
def verify_hour_entry(entryId):
    authenticate()
    authorize(["SiteSupervisor"])
    entry = get_hour_entry_or_404(entryId)
    get_body()
    assignment = db.assignments[entry["assignment_id"]]
    incident_gate(db.incidents[assignment["incident_id"]], "hour entry verification", demob_allowed=True)
    if entry["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"Hour entry must be SUBMITTED to verify (current: {entry['status']})")
    _sod_hour_check(entry)
    entry["status"] = "VERIFIED"
    entry["verified_by_user_id"] = g.user_id
    svc.touch(entry)
    svc.touch(db.volunteers[assignment["volunteer_id"]])  # verified_hours_total recompute
    return success_object(svc.hour_entry_view(entry))


@bp.post("/vrc/hour-entries/<entryId>/dispute")
def dispute_hour_entry(entryId):
    authenticate()
    authorize(["SiteSupervisor"])
    entry = get_hour_entry_or_404(entryId)
    body = get_body()
    check_unknown_fields(body, {"reason"})
    reason = req_string(body, "reason")
    assignment = db.assignments[entry["assignment_id"]]
    incident_gate(db.incidents[assignment["incident_id"]], "hour entry dispute", demob_allowed=True)
    if entry["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"Hour entry must be SUBMITTED to dispute (current: {entry['status']})")
    _sod_hour_check(entry)
    entry["dispute_count"] += 1
    entry["dispute_reason"] = reason
    if entry["dispute_count"] >= 2:
        # Second dispute after a resubmission settles the entry terminally.
        entry["status"] = "REJECTED_FINAL"
    else:
        entry["status"] = "DISPUTED"
    svc.touch(entry)
    return success_object(svc.hour_entry_view(entry))


@bp.post("/vrc/hour-entries/<entryId>/resubmit")
def resubmit_hour_entry(entryId):
    authenticate()
    authorize(["Volunteer", "SiteSupervisor"])
    entry = get_hour_entry_or_404(entryId)
    body = get_body()
    check_unknown_fields(body, {"hours"})
    hours = req_hours(body, "hours")
    assignment = db.assignments[entry["assignment_id"]]
    incident_gate(db.incidents[assignment["incident_id"]], "hour entry resubmission", demob_allowed=True)
    if entry["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE, f"Hour entry must be DISPUTED to resubmit (current: {entry['status']})")
    if g.role == "Volunteer" and g.user_id != assignment["volunteer_id"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "Volunteer callers may only resubmit their own entries")
    shift = db.shifts[assignment["site_shift_id"]]
    check_hours_within_shift(hours, shift)
    entry["hours"] = hours
    entry["status"] = "SUBMITTED"
    entry["resubmit_count"] += 1
    entry["entry_value_cents"] = svc.entry_value_cents(entry, assignment)
    # submitted_by_user_id deliberately unchanged: the original submitter
    # remains the segregation-of-duties target for the life of the entry.
    svc.touch(entry)
    return success_object(svc.hour_entry_view(entry))


@bp.get("/vrc/assignments/<assignmentId>/hour-entries")
def list_assignment_hour_entries(assignmentId):
    authenticate()
    authorize(ALL_ROLES)
    assignment = get_assignment_or_404(assignmentId)
    records = [e for e in db.hour_entries.values() if e["assignment_id"] == assignment["id"]]
    status = request.args.get("status")
    if status is not None:
        records = [e for e in records if e["status"] == status]
    window, page = paginate(records, request.args)
    return success_list([svc.hour_entry_view(e) for e in window], page)


# --- RiskReport -------------------------------------------------------------------------------

@bp.post("/vrc/risk-reports")
def create_risk_report():
    authenticate()
    authorize(["SiteSupervisor", "IntakeCoordinator", "LogisticsCoordinator"])
    body = get_body()
    subject_id = load_fk_string(body, "subject_volunteer_id", db.volunteers, "Volunteer")
    check_unknown_fields(body, {"subject_volunteer_id", "severity", "category", "description", "occurred_at"})
    if not isinstance(subject_id, str) or not subject_id:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: subject_volunteer_id")
    severity = req_enum(body, "severity", SEVERITIES)
    category = req_enum(body, "category", RISK_CATEGORIES)
    description = req_string(body, "description")
    occurred_at = req_datetime(body, "occurred_at")
    subject = db.volunteers[subject_id]
    incident_gate(db.incidents[subject["incident_id"]], "risk report filing")
    rec = svc.create_record(db.risk_reports, {
        "subject_volunteer_id": subject_id,
        "reporter_user_id": g.user_id,
        "severity": severity,
        "category": category,
        "description": description,
        "occurred_at": occurred_at,
        "status": "FILED",
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
        "points_awarded": None,
    })
    return success_object(svc.risk_report_view(rec), 201)


def _sod_risk_check(report):
    if g.user_id == report["reporter_user_id"]:
        raise_error(ERR_SOD_RISK_ADJUDICATION, "The reporter of a risk report may not adjudicate it")


@bp.post("/vrc/risk-reports/<reportId>/substantiate")
def substantiate_risk_report(reportId):
    authenticate()
    authorize(["RiskOfficer"])
    report = get_risk_report_or_404(reportId)
    get_body()
    subject = db.volunteers[report["subject_volunteer_id"]]
    incident = db.incidents[subject["incident_id"]]
    incident_gate(incident, "risk report substantiation", demob_allowed=True)
    if report["status"] != "FILED":
        raise_error(ERR_INVALID_STATE, f"Risk report must be FILED to substantiate (current: {report['status']})")
    _sod_risk_check(report)
    report["status"] = "SUBSTANTIATED"
    report["adjudicated_by_user_id"] = g.user_id
    report["adjudicated_at"] = db.now()
    report["points_awarded"] = svc.SEVERITY_POINTS[report["severity"]]
    svc.touch(report)
    current, _ = svc.risk_scores(subject["id"])
    svc.touch(subject)  # risk scores recomputed
    if current >= svc.SUSPEND_THRESHOLD and subject["status"] in ("CLEARED", "READY", "DEPLOYED"):
        subject["status"] = "SUSPENDED"
        svc.touch(subject)
        svc.suspension_cascade(subject)
    else:
        svc.recompute_posture(incident)
    return success_object(svc.risk_report_view(report))


@bp.post("/vrc/risk-reports/<reportId>/dismiss")
def dismiss_risk_report(reportId):
    authenticate()
    authorize(["RiskOfficer"])
    report = get_risk_report_or_404(reportId)
    get_body()
    subject = db.volunteers[report["subject_volunteer_id"]]
    incident_gate(db.incidents[subject["incident_id"]], "risk report dismissal", demob_allowed=True)
    if report["status"] != "FILED":
        raise_error(ERR_INVALID_STATE, f"Risk report must be FILED to dismiss (current: {report['status']})")
    _sod_risk_check(report)
    report["status"] = "DISMISSED"
    report["adjudicated_by_user_id"] = g.user_id
    report["adjudicated_at"] = db.now()
    svc.touch(report)
    return success_object(svc.risk_report_view(report))
