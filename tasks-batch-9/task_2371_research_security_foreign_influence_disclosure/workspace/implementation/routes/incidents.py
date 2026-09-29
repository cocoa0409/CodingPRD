"""Security incidents: investigation, notification and closure (PRD 3.8)."""

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import AGENCY_LIAISON, RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("incidents", __name__)

INCIDENT_TRANSITIONS = (
    ("REPORTED", "INVESTIGATING"),
    ("REPORTED", "UNSUBSTANTIATED"),
    ("INVESTIGATING", "SUBSTANTIATED"),
    ("INVESTIGATING", "UNSUBSTANTIATED"),
    ("SUBSTANTIATED", "CLOSED"),
    ("AGENCY_NOTIFIED", "CLOSED"),
)


@bp.post("/security-incidents")
def create_incident():
    require(RSO)
    data = validate.body()

    # step 5 — body foreign keys in declaration order
    investigator = must_exist("investigator", data.get("investigator_id"))
    disclosure = None
    if data.get("disclosure_id") is not None:
        disclosure = must_exist("disclosure", data.get("disclosure_id"))
    project = None
    if data.get("project_id") is not None:
        project = must_exist("project", data.get("project_id"))

    incident_type = validate.req_enum(data, "incident_type", E.INCIDENT_TYPES)
    discovered_on = validate.req_instant(data, "discovered_on")
    summary = validate.req_string(data, "summary")

    record = db.base_record()
    record.update({
        "investigator_id": investigator["id"],
        "disclosure_id": disclosure["id"] if disclosure else None,
        "project_id": project["id"] if project else None,
        "incident_type": incident_type,
        "discovered_on": discovered_on,
        "summary": summary,
        "status": "REPORTED",
        "finding": "NONE",
        "severity_points": None,
        "severity": None,
        "lead_investigator_user_id": None,
        "substantiated_at": None,
        "notification_due_on": None,
        "agency_notified_on": None,
        "notification_reference": None,
        "notified_late": False,
        "closed_at": None,
    })
    db.incidents[record["id"]] = record
    if project is not None:
        cascade.recompute_project(project)
    return response.object_response(present.incident(record), 201)


@bp.get("/security-incidents/<incident_id>")
def read_incident(incident_id):
    require_any()
    record = must_exist("incident", incident_id)
    return response.object_response(present.incident(record))


@bp.get("/security-incidents")
def list_incidents():
    require_any()
    investigator_id = validate.filter_value("investigator_id")
    disclosure_id = validate.filter_value("disclosure_id")
    project_id = validate.filter_value("project_id")
    status = validate.filter_enum("status", E.INCIDENT_STATUSES)

    rows = []
    for record in db.ordered(db.incidents.values()):
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if disclosure_id and record["disclosure_id"] != disclosure_id:
            continue
        if project_id and record["project_id"] != project_id:
            continue
        if status and record["status"] != status:
            continue
        rows.append(record)
    return render_list(rows, present.incident)


def _critical_project_cascade(investigator_id):
    """CRITICAL severity drags every cleared project of the investigator down."""
    seen = []
    for row in db.ordered(db.personnel.values()):
        if row["investigator_id"] != investigator_id or row["status"] != "ACTIVE":
            continue
        if row["project_id"] in seen:
            continue
        seen.append(row["project_id"])
    for project_id in seen:
        project = db.projects.get(project_id)
        if project is None:
            continue
        cascade.suspend_project_security(project, "INCIDENT_NOTIFICATION")


@bp.post("/security-incidents/<incident_id>/status")
def set_incident_status(incident_id):
    user_id, _role = require(RSO)
    data = validate.body()
    record = must_exist("incident", incident_id)

    to_status = validate.req_enum(data, "to_status", E.INCIDENT_STATUSES)
    lead = validate.opt_string(data, "lead_investigator_user_id")
    if to_status == "INVESTIGATING" and not lead:
        validate.bad("Field 'lead_investigator_user_id' is required to open an "
                     "investigation.")

    current = record["status"]
    if (current, to_status) not in INCIDENT_TRANSITIONS:
        raise ApiError("ERR_INVALID_INCIDENT_TRANSITION",
                       "Incident status cannot move %s -> %s."
                       % (current, to_status))

    investigator = db.investigators.get(record["investigator_id"])
    project = db.projects.get(record["project_id"]) if record["project_id"] \
        else None

    if to_status == "INVESTIGATING":
        record["status"] = "INVESTIGATING"
        record["lead_investigator_user_id"] = lead
        db.touch(record)

    elif to_status == "UNSUBSTANTIATED":
        # step 10 — only the stored lead may record a finding once named
        if current == "INVESTIGATING" and \
                record["lead_investigator_user_id"] != user_id:
            raise ApiError("ERR_NOT_INCIDENT_LEAD",
                           "Only the stored investigation lead may record a "
                           "finding.")
        record["status"] = "UNSUBSTANTIATED"
        record["finding"] = "UNSUBSTANTIATED"
        db.touch(record)
        if project is not None:
            cascade.recompute_project(project)

    elif to_status == "SUBSTANTIATED":
        if record["lead_investigator_user_id"] != user_id:
            raise ApiError("ERR_NOT_INCIDENT_LEAD",
                           "Only the stored investigation lead may substantiate "
                           "an incident.")
        record["status"] = "SUBSTANTIATED"
        record["finding"] = "SUBSTANTIATED"
        record["substantiated_at"] = db.clock_str()
        derive.freeze_severity(record)
        db.touch(record)
        if project is not None:
            cascade.recompute_project(project)
        cascade.apply_posture_cascade(investigator)
        if record["severity"] == "CRITICAL":
            _critical_project_cascade(record["investigator_id"])

    else:  # CLOSED
        if current == "SUBSTANTIATED":
            raise ApiError("ERR_AGENCY_NOTIFICATION_REQUIRED",
                           "A substantiated incident must be notified to the "
                           "agency before closure.")
        remediation = None
        if record["disclosure_id"]:
            remediation = db.disclosures.get(record["disclosure_id"])
        complete = False
        if remediation is not None and remediation["review_status"] == "CERTIFIED":
            for item in derive.disclosure_items(remediation["id"]):
                if item["source"] == "INCIDENT_REMEDIATION" and \
                        item["status"] != "WITHDRAWN":
                    complete = True
                    break
        if not complete:
            raise ApiError("ERR_REMEDIATION_INCOMPLETE",
                           "The remediation disclosure leg is not complete.")
        record["status"] = "CLOSED"
        record["closed_at"] = db.clock_str()
        db.touch(record)
        if project is not None:
            cascade.recompute_project(project)
        cascade.recompute_investigator(investigator)

    return response.object_response(present.incident(record))


@bp.post("/security-incidents/<incident_id>/notify")
def notify_incident(incident_id):
    user_id, _role = require(AGENCY_LIAISON)
    data = validate.body()
    record = must_exist("incident", incident_id)

    notified_on = validate.req_instant(data, "agency_notified_on")
    reference = validate.req_string(data, "notification_reference")

    if record["status"] != "SUBSTANTIATED":
        raise ApiError("ERR_INVALID_INCIDENT_TRANSITION",
                       "Only a SUBSTANTIATED incident may be notified.")

    # step 9 — segregation of duties
    if record["lead_investigator_user_id"] is not None and \
            record["lead_investigator_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The investigation lead may not notify the agency.")

    substantiated_date = util.parse_date(record["substantiated_at"])
    notified_date = util.parse_date(notified_on)
    if substantiated_date is not None and notified_date < substantiated_date:
        raise ApiError("ERR_INVALID_NOTIFICATION_DATE",
                       "agency_notified_on must fall on or after the "
                       "substantiation date.")

    record["status"] = "AGENCY_NOTIFIED"
    record["agency_notified_on"] = notified_on
    record["notification_reference"] = reference
    due_date = util.parse_date(record["notification_due_on"])
    record["notified_late"] = bool(due_date is not None and
                                   notified_date > due_date)
    db.touch(record)

    project = db.projects.get(record["project_id"]) if record["project_id"] \
        else None
    if project is not None:
        cascade.recompute_project(project)
    cascade.apply_posture_cascade(db.investigators.get(record["investigator_id"]))
    return response.object_response(present.incident(record))
