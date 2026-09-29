"""Incident reports: severity, triage and the retaliation dimension (PRD 3.5 / 3.6)."""

from flask import Blueprint

import calc
import constants as C
import sync
from db import new_row, store
from errors import ApiError
from middleware import authenticate
from routes.common import filtered, lookup, paged, single
from validation import (bad, bool_field, body, dt_field, enum_field, id_field,
                        qs_enum, qs_str, str_field)

bp = Blueprint("reports", __name__)

READ_REPORT_ROLES = ("SafetyOfficer", "SiteManager", "ThreatTeamLead", "ThreatTeamMember",
                     "HRPartner", "ComplianceAuditor", "ProgramAdmin")


@bp.post("/incident-reports")
def create_report():
    authenticate(("Employee", "SiteManager", "SafetyOfficer", "Anonymous"))
    data = body()
    worksite_id = id_field(data, "worksite_id", True)
    work_area_id = id_field(data, "work_area_id", True)
    reporter_employee_id = id_field(data, "reporter_employee_id", False)
    subject_employee_id = id_field(data, "subject_employee_id", False)
    channel = enum_field(data, "channel", C.REPORT_CHANNELS, True)
    occurred_at, occurred_dt = dt_field(data, "occurred_at", True)
    narrative = str_field(data, "narrative", True, 10, 4000)
    incident_type = enum_field(data, "incident_type", C.INCIDENT_TYPES, True)
    weapon_involved = bool_field(data, "weapon_involved", False, False)
    injury_level = enum_field(data, "injury_level", C.INJURY_LEVELS, False, "NONE")

    if occurred_dt is not None and occurred_dt > store.clock:
        bad("Field 'occurred_at' must not be after the logical clock.")

    lookup(store.worksites, worksite_id, "ERR_WORKSITE_NOT_FOUND")
    lookup(store.work_areas, work_area_id, "ERR_WORK_AREA_NOT_FOUND")
    if reporter_employee_id is not None:
        lookup(store.employees, reporter_employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    if subject_employee_id is not None:
        lookup(store.employees, subject_employee_id, "ERR_EMPLOYEE_NOT_FOUND")

    # Step 20 -- the reporting-channel conditional rule.
    if channel == "ANONYMOUS_DROPBOX":
        if reporter_employee_id is not None:
            raise ApiError("ERR_REPORTER_REQUIRED",
                           "An ANONYMOUS_DROPBOX report must not name a reporter.")
    elif reporter_employee_id is None:
        raise ApiError("ERR_REPORTER_REQUIRED", "This channel requires a reporter.")

    row = new_row({
        "worksite_id": worksite_id,
        "work_area_id": work_area_id,
        "reporter_employee_id": reporter_employee_id,
        "subject_employee_id": subject_employee_id,
        "triaged_by_employee_id": None,
        "channel": channel,
        "occurred_at": occurred_at,
        "narrative": narrative,
        "incident_type": incident_type,
        "weapon_involved": weapon_involved,
        "injury_level": injury_level,
        "severity_points": 0,
        "severity_class": "MINOR",
        "log_required": False,
        "triage_status": "NEW",
        "retaliation_status": "NOT_ALLEGED",
        "retaliation_claimant_employee_id": None,
    })
    row.update(calc.incident_severity(row))
    store.incident_reports[row["id"]] = row
    return single(row, 201)


@bp.get("/incident-reports/<incident_report_id>")
def get_report(incident_report_id):
    authenticate(READ_REPORT_ROLES)
    return single(lookup(store.incident_reports, incident_report_id, "ERR_INCIDENT_REPORT_NOT_FOUND"))


@bp.get("/incident-reports")
def list_reports():
    authenticate(READ_REPORT_ROLES)
    filters = {
        "worksite_id": qs_str("worksite_id"),
        "work_area_id": qs_str("work_area_id"),
        "reporter_employee_id": qs_str("reporter_employee_id"),
        "subject_employee_id": qs_str("subject_employee_id"),
        "triaged_by_employee_id": qs_str("triaged_by_employee_id"),
        "retaliation_claimant_employee_id": qs_str("retaliation_claimant_employee_id"),
        "channel": qs_enum("channel", C.REPORT_CHANNELS),
        "severity_class": qs_enum("severity_class", C.SEVERITY_CLASSES),
        "triage_status": qs_enum("triage_status", C.TRIAGE_STATUSES),
        "retaliation_status": qs_enum("retaliation_status", C.RETALIATION_STATUSES),
    }
    return paged(filtered(list(store.incident_reports.values()), filters))


@bp.post("/incident-reports/<incident_report_id>/triage")
def triage_report(incident_report_id):
    caller = authenticate(("SafetyOfficer",))
    data = body()
    disposition = enum_field(data, "disposition", ("ESCALATE", "NO_ACTION"), True)
    str_field(data, "triage_note", False)

    report = lookup(store.incident_reports, incident_report_id, "ERR_INCIDENT_REPORT_NOT_FOUND")

    if report["triage_status"] != "NEW":
        raise ApiError("ERR_REPORT_INVALID_STATE", "Only a NEW report may be triaged.")

    severity = calc.incident_severity(report)
    if disposition == "NO_ACTION" and severity["severity_class"] != "MINOR":
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "NO_ACTION is only permitted on a MINOR report.")

    values = dict(severity)
    values["triaged_by_employee_id"] = caller.user_id
    values["triage_status"] = "ESCALATED" if disposition == "ESCALATE" else "CLOSED_NO_ACTION"
    sync.assign(report, values)
    return single(report)


@bp.post("/incident-reports/<incident_report_id>/retaliation-updates")
def retaliation_update(incident_report_id):
    caller = authenticate(("Employee", "HRPartner"))
    data = body()
    action = enum_field(data, "action", ("ALLEGE", "OPEN_REVIEW", "SUBSTANTIATE", "DISMISS"), True)
    str_field(data, "statement", False)

    report = lookup(store.incident_reports, incident_report_id, "ERR_INCIDENT_REPORT_NOT_FOUND")

    # Step 7 -- the claimant's own act; an HRPartner may act on their behalf.
    if caller.role == "Employee" and report.get("reporter_employee_id") != caller.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This report was filed by another employee.")

    current = report["retaliation_status"]
    values = {}
    if action == "ALLEGE":
        if current != "NOT_ALLEGED" or report.get("reporter_employee_id") is None:
            raise ApiError("ERR_RETALIATION_INVALID_STATE",
                           "ALLEGE requires a NOT_ALLEGED report that names a reporter.")
        values["retaliation_status"] = "ALLEGED"
        values["retaliation_claimant_employee_id"] = report["reporter_employee_id"]
    elif action == "OPEN_REVIEW":
        if current != "ALLEGED":
            raise ApiError("ERR_RETALIATION_INVALID_STATE", "OPEN_REVIEW applies only from ALLEGED.")
        values["retaliation_status"] = "UNDER_REVIEW"
    elif action == "SUBSTANTIATE":
        if current != "UNDER_REVIEW":
            raise ApiError("ERR_RETALIATION_INVALID_STATE",
                           "SUBSTANTIATE applies only from UNDER_REVIEW.")
        values["retaliation_status"] = "SUBSTANTIATED"
    else:
        if current not in ("ALLEGED", "UNDER_REVIEW"):
            raise ApiError("ERR_RETALIATION_INVALID_STATE",
                           "DISMISS applies only from ALLEGED or UNDER_REVIEW.")
        values["retaliation_status"] = "UNSUBSTANTIATED"

    sync.assign(report, values)
    return single(report)
