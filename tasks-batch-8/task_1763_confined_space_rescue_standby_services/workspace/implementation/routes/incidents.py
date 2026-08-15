"""Incident reporting and workflow (PRD section 3.6)."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ERR_INCIDENT_INVALID_STATE, ERR_INCIDENT_NOT_FOUND,
    ERR_PERMIT_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES, raise_error,
)
from helpers import (
    body, list_response, now_dt, opt_enum, reject_unknown, req_enum,
    req_string, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.permits import get_permit
from services import cancel_permit_cascade, emergency_suspend, space_of_permit

bp = Blueprint("incidents", __name__)

SEVERITIES = ("MINOR", "SERIOUS", "CRITICAL")
KINDS = ("ENTRAPMENT", "ATMOSPHERE", "MEDICAL", "EQUIPMENT")


def get_incident(incident_id):
    incident = db.incidents.get(incident_id)
    if incident is None:
        raise_error(ERR_INCIDENT_NOT_FOUND, "Incident not found")
    return incident


@bp.route("/rescue-ops/entry-permits/<permit_id>/incidents", methods=["POST"])
def report_incident(permit_id):
    user_id, _, _ = require_auth(("EntrySupervisor", "SafetyOfficer", "RescueTeamLead"))
    permit = get_permit(permit_id)
    data = body()
    reject_unknown(data, {"severity", "kind", "description"})
    severity = req_enum(data, "severity", SEVERITIES)
    kind = req_enum(data, "kind", KINDS)
    description = req_string(data, "description")
    if permit["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_PERMIT_INVALID_STATE,
                    "Incidents may be reported only on ACTIVE or SUSPENDED permits")
    incident = {
        "permit_id": permit["id"],
        "reported_by": user_id,
        "severity": severity,
        "kind": kind,
        "description": description,
        "triaged_by": None,
        "resolved_by": None,
        "resolution_notes": None,
        "escalation_level": 0,
        "status": "REPORTED",
    }
    stamp_new(incident)
    db.incidents[incident["id"]] = incident
    if permit["status"] == "ACTIVE":
        # Reporting on an ACTIVE permit forces an emergency suspension.
        emergency_suspend(permit, now_dt())
    return success_object(serializers.incident(incident), 201)


@bp.route("/rescue-ops/incidents", methods=["GET"])
def list_incidents():
    require_auth(ALL_ROLES)
    return list_response(list(db.incidents.values()), serializers.incident, {
        "permit_id": request.args.get("permit_id"),
        "status": request.args.get("status"),
        "severity": request.args.get("severity"),
        "reported_by": request.args.get("reported_by"),
    })


@bp.route("/rescue-ops/incidents/<incident_id>", methods=["GET"])
def get_one_incident(incident_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.incident(get_incident(incident_id)))


@bp.route("/rescue-ops/incidents/<incident_id>/triage", methods=["POST"])
def triage_incident(incident_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    incident = get_incident(incident_id)
    data = body()
    reject_unknown(data, {"severity"})
    severity = opt_enum(data, "severity", SEVERITIES, None)
    if incident["status"] not in ("REPORTED", "REOPENED"):
        raise_error(ERR_INCIDENT_INVALID_STATE,
                    "Only a REPORTED or REOPENED incident can be triaged")
    incident["status"] = "TRIAGED"
    incident["triaged_by"] = user_id
    if severity is not None:
        incident["severity"] = severity
    touch(incident)
    return success_object(serializers.incident(incident))


@bp.route("/rescue-ops/incidents/<incident_id>/escalate", methods=["POST"])
def escalate_incident(incident_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    incident = get_incident(incident_id)
    body()
    if incident["status"] != "TRIAGED":
        raise_error(ERR_INCIDENT_INVALID_STATE, "Only a TRIAGED incident can be escalated")
    now = now_dt()
    incident["status"] = "ESCALATED"
    incident["escalation_level"] += 1
    touch(incident)
    # Escalation cascade link 1: cancel the parent permit (link 2 side effects
    # fire inside the cascade); CRITICAL severity takes the space out of service.
    permit = get_permit(incident["permit_id"])
    if permit["status"] in ("DRAFT", "ISSUED", "ACTIVE", "SUSPENDED"):
        cancel_permit_cascade(permit, now, escalation=True)
    if incident["severity"] == "CRITICAL":
        space = space_of_permit(permit)
        if space is not None and space["status"] != "OUT_OF_SERVICE":
            space["status"] = "OUT_OF_SERVICE"
            touch(space)
    return success_object(serializers.incident(incident))


@bp.route("/rescue-ops/incidents/<incident_id>/resolve", methods=["POST"])
def resolve_incident(incident_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    incident = get_incident(incident_id)
    data = body()
    reject_unknown(data, {"resolution_notes"})
    resolution_notes = req_string(data, "resolution_notes")
    if incident["status"] not in ("TRIAGED", "ESCALATED"):
        raise_error(ERR_INCIDENT_INVALID_STATE,
                    "Only a TRIAGED or ESCALATED incident can be resolved")
    if user_id == incident["reported_by"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "The incident reporter may not resolve it")
    incident["status"] = "RESOLVED"
    incident["resolved_by"] = user_id
    incident["resolution_notes"] = resolution_notes
    touch(incident)
    return success_object(serializers.incident(incident))


@bp.route("/rescue-ops/incidents/<incident_id>/reopen", methods=["POST"])
def reopen_incident(incident_id):
    user_id, _, _ = require_auth(("SafetyOfficer",))
    incident = get_incident(incident_id)
    data = body()
    reject_unknown(data, {"reason"})
    req_string(data, "reason")
    if incident["status"] != "RESOLVED":
        raise_error(ERR_INCIDENT_INVALID_STATE, "Only a RESOLVED incident can be reopened")
    incident["status"] = "REOPENED"
    touch(incident)
    return success_object(serializers.incident(incident))
