"""Incident adjudication, insurance coverage and safety cascades (PRD 3.9)."""

from flask import Blueprint

import calc
import derive
from auth import require
from db import by_created, db, new_record, today_str, touch
from errors import fail
from response import created, listing, ok
from validation import f_datetime, f_enum, f_str, get_body, pagination, paginate, q_enum, q_str

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "MODERATE", "CRITICAL")
INJURY_TYPES = ("NONE", "LACERATION", "FRACTURE", "BURN", "STRAIN", "EXPOSURE")
INCIDENT_STATUSES = ("REPORTED", "SUBSTANTIATED", "UNSUBSTANTIATED", "CLOSED")
FINDINGS = ("SUBSTANTIATED", "UNSUBSTANTIATED")
RECORDABLE_SEVERITIES = ("MODERATE", "CRITICAL")


def _osha_recordable(incident):
    return bool(incident["status"] in ("SUBSTANTIATED", "CLOSED")
                and incident["severity"] in RECORDABLE_SEVERITIES
                and incident["injury_type"] != "NONE")


@bp.post("/incident-reports")
def report_incident():
    user_id, _role = require("WblCoordinator", "EmployerSupervisor", "Student")
    body = get_body()
    placement = derive.get_placement(f_str(body, "placement_id"))
    worksite = derive.get_worksite(f_str(body, "worksite_id"))
    occurred_at = f_datetime(body, "occurred_at")
    severity = f_enum(body, "severity", SEVERITIES)
    description = f_str(body, "description")
    injury_type = f_enum(body, "injury_type", INJURY_TYPES)

    # step 16
    if placement["lifecycle_status"] != "ACTIVE":
        fail("ERR_PLACEMENT_NOT_ACTIVE", "The placement is not active.")
    # step 43
    if worksite["id"] != placement["worksite_id"]:
        fail("ERR_AGREEMENT_WORKSITE_MISMATCH",
             "The incident worksite does not match the placement's worksite.")

    incident = new_record()
    incident.update({
        "placement_id": placement["id"],
        "worksite_id": worksite["id"],
        "occurred_at": occurred_at,
        "severity": severity,
        "description": description,
        "injury_type": injury_type,
        "reported_by_user_id": user_id,
        "status": "REPORTED",
        "coverage_determination": "PENDING",
        "determined_by_user_id": None,
        "closed_on": None,
        "osha_recordable": False,
    })
    db.incident_reports[incident["id"]] = incident
    return created(incident)


@bp.post("/incident-reports/<incidentId>/finding")
def record_finding(incidentId):
    require("ComplianceOfficer")
    incident = derive.get_incident(incidentId)
    body = get_body()
    finding = f_enum(body, "finding", FINDINGS)

    if incident["status"] != "REPORTED":
        fail("ERR_INCIDENT_INVALID_STATE",
             "Only a reported incident may receive an investigation finding.")

    if finding == "UNSUBSTANTIATED":
        incident["status"] = "UNSUBSTANTIATED"
        incident["coverage_determination"] = "NOT_COVERED"
        incident["closed_on"] = today_str()
        incident["osha_recordable"] = _osha_recordable(incident)
        touch(incident)
        return ok(incident)

    incident["status"] = "SUBSTANTIATED"
    incident["osha_recordable"] = _osha_recordable(incident)
    touch(incident)

    worksite = derive.get_worksite(incident["worksite_id"])
    partner = derive.partner_of_worksite(worksite)

    if incident["severity"] == "CRITICAL":
        derive.fail_worksite(worksite)
        if partner is not None:
            derive.recompute_partner_safety(partner)
        derive.block_placements_of_worksite(worksite["id"])
    else:
        if partner is not None:
            derive.recompute_partner_safety(partner)
        derive.flag_placements_of_worksite(worksite["id"])

    return ok(incident)


@bp.post("/incident-reports/<incidentId>/coverage")
def record_coverage(incidentId):
    user_id, _role = require("ComplianceOfficer")
    incident = derive.get_incident(incidentId)

    if incident["status"] != "SUBSTANTIATED":
        fail("ERR_INCIDENT_INVALID_STATE",
             "Only a substantiated incident may receive a coverage determination.")

    placement = derive.get_placement(incident["placement_id"])
    agreement = db.agreements.get(placement["agreement_id"])
    partner = derive.partner_of_placement(placement)

    determination = calc.insurance_coverage_determination(incident, placement,
                                                          agreement, partner)
    incident["status"] = "CLOSED"
    incident["coverage_determination"] = determination
    incident["determined_by_user_id"] = user_id
    incident["closed_on"] = today_str()
    incident["osha_recordable"] = _osha_recordable(incident)
    touch(incident)
    return ok(incident)


@bp.get("/incident-reports/<incidentId>")
def read_incident(incidentId):
    require("WblCoordinator", "ComplianceOfficer", "SafetyReviewer")
    return ok(derive.get_incident(incidentId))


@bp.get("/incident-reports")
def list_incidents():
    require("WblCoordinator", "ComplianceOfficer", "SafetyReviewer")
    limit, offset = pagination()
    placement_id = q_str("placement_id")
    worksite_id = q_str("worksite_id")
    status = q_enum("status", INCIDENT_STATUSES)
    severity = q_enum("severity", SEVERITIES)

    rows = []
    for incident in db.incident_reports.values():
        if placement_id is not None and incident["placement_id"] != placement_id:
            continue
        if worksite_id is not None and incident["worksite_id"] != worksite_id:
            continue
        if status is not None and incident["status"] != status:
            continue
        if severity is not None and incident["severity"] != severity:
            continue
        rows.append(incident)

    page, total = paginate(by_created(rows), limit, offset)
    return listing(page, total, limit, offset)
