"""Quality-assurance incident intake, review and the substantiate / dismiss fork."""

from flask import Blueprint

from db import clock, db
from errors import ApiError
from middleware import auth, json_body
from response import ok, paginate
from util import opt_str, req_enum, req_str

from services.cascade import set_provider_status, transition_allowed
from services.core import new_row, s_incident, sort_created, touch
from routes._common import (
    CATEGORIES,
    INCIDENT_STATUSES,
    QA_ACTIONS,
    SEVERITIES,
    keep,
    need,
    qs_enum,
    qs_str,
)

bp = Blueprint("incidents", __name__)

INCIDENT_TERMINAL = ("SUBSTANTIATED", "DISMISSED")

QA_TARGET = {
    "PROBATION": "PROBATION",
    "SUSPENSION": "SUSPENDED",
    "DEPROVISION": "DEPROVISIONED",
}


@bp.post("/incident-reports")
def create_incident():
    body = json_body()
    provider_id = req_str(body, "provider_id")
    reservation_id = opt_str(body, "reservation_id")
    severity = req_enum(body, "severity", SEVERITIES)
    category = req_enum(body, "category", CATEGORIES)
    narrative = req_str(body, "narrative", 2000)

    user_id, _role = auth(
        "care_coordinator", "benefits_admin", "employee_user", "network_admin"
    )

    provider = need(db.providers, provider_id, "ERR_PROVIDER_NOT_FOUND")
    reservation = None
    if reservation_id is not None:
        reservation = need(db.reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
        if reservation["matched_provider_id"] != provider["id"]:
            raise ApiError("ERR_INCIDENT_PROVIDER_MISMATCH")

    incident = new_row(
        {
            "provider_id": provider["id"],
            "reservation_id": reservation["id"] if reservation is not None else None,
            "severity": severity,
            "category": category,
            "narrative": narrative,
            "reported_by_user_id": user_id,
            "reported_at": clock(),
            "incident_status": "OPEN",
            "qa_action": "NONE",
            "reviewed_by": None,
            "resolution_reason_code": None,
        }
    )
    db.incident_reports[incident["id"]] = incident
    return ok(s_incident(incident), 201)


@bp.get("/incident-reports/<row_id>")
def get_incident(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator")
    incident = need(db.incident_reports, row_id, "ERR_INCIDENTREPORT_NOT_FOUND")
    return ok(s_incident(incident))


@bp.get("/incident-reports")
def list_incidents():
    auth("network_admin", "benefits_admin", "care_coordinator")
    provider_id = qs_str("provider_id")
    reservation_id = qs_str("reservation_id")
    incident_status = qs_enum("incident_status", INCIDENT_STATUSES)
    severity = qs_enum("severity", SEVERITIES)
    category = qs_enum("category", CATEGORIES)
    rows = sort_created(list(db.incident_reports.values()))
    rows = keep(rows, "provider_id", provider_id)
    rows = keep(rows, "reservation_id", reservation_id)
    rows = keep(rows, "incident_status", incident_status)
    rows = keep(rows, "severity", severity)
    rows = keep(rows, "category", category)
    return paginate(rows, s_incident)


@bp.post("/incident-reports/<row_id>/review")
def review_incident(row_id):
    json_body()
    user_id, _role = auth("care_coordinator", "network_admin")
    incident = need(db.incident_reports, row_id, "ERR_INCIDENTREPORT_NOT_FOUND")

    if incident["incident_status"] in INCIDENT_TERMINAL:
        raise ApiError("ERR_INCIDENTREPORT_TERMINAL")
    if incident["incident_status"] != "OPEN":
        raise ApiError("ERR_INCIDENTREPORT_STATE_INVALID")

    provider = db.providers.get(incident["provider_id"])
    if provider is None or provider["network_status"] == "DEPROVISIONED":
        raise ApiError("ERR_PROVIDER_NOT_IN_NETWORK")

    incident["incident_status"] = "UNDER_REVIEW"
    incident["reviewed_by"] = user_id
    touch(incident)
    return ok(s_incident(incident))


@bp.post("/incident-reports/<row_id>/substantiate")
def substantiate_incident(row_id):
    body = json_body()
    qa_action = req_enum(body, "qa_action", QA_ACTIONS)
    resolution_reason_code = req_str(body, "resolution_reason_code", 80)

    user_id, _role = auth("network_admin")
    incident = need(db.incident_reports, row_id, "ERR_INCIDENTREPORT_NOT_FOUND")

    if incident["reported_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if incident["incident_status"] in INCIDENT_TERMINAL:
        raise ApiError("ERR_INCIDENTREPORT_TERMINAL")
    if incident["incident_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENTREPORT_STATE_INVALID")

    provider = db.providers.get(incident["provider_id"])
    target = QA_TARGET.get(qa_action)
    if target is not None:
        if provider is None or not transition_allowed(
            provider["network_status"], target
        ):
            raise ApiError("ERR_PROVIDER_STATE_INVALID")

    incident["incident_status"] = "SUBSTANTIATED"
    incident["qa_action"] = qa_action
    incident["resolution_reason_code"] = resolution_reason_code
    touch(incident)

    if target is not None:
        # PRD 3.3: CREDENTIALED -> PROBATION records last_status_reason_code from
        # INCIDENT_SUBSTANTIATED when the demotion is driven by a substantiated
        # incident; the other targets record the supplied reason code.
        reason = (
            "INCIDENT_SUBSTANTIATED" if target == "PROBATION" else resolution_reason_code
        )
        set_provider_status(provider, target, reason)

    return ok(s_incident(incident))


@bp.post("/incident-reports/<row_id>/dismiss")
def dismiss_incident(row_id):
    body = json_body()
    resolution_reason_code = req_str(body, "resolution_reason_code", 80)

    user_id, _role = auth("network_admin")
    incident = need(db.incident_reports, row_id, "ERR_INCIDENTREPORT_NOT_FOUND")

    if incident["reported_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if incident["incident_status"] in INCIDENT_TERMINAL:
        raise ApiError("ERR_INCIDENTREPORT_TERMINAL")
    if incident["incident_status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENTREPORT_STATE_INVALID")

    incident["incident_status"] = "DISMISSED"
    incident["qa_action"] = "NONE"
    incident["resolution_reason_code"] = resolution_reason_code
    touch(incident)
    return ok(s_incident(incident))
