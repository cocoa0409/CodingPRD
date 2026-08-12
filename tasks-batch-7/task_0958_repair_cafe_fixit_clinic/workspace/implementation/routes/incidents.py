"""SafetyIncident reporting, resolution (with suspension cascade), dismissal."""

from flask import Blueprint, g

import db
import serializers as ser
import services
from errors import (
    ERR_EVENT_NOT_FOUND,
    ERR_FIXER_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INVALID_INCIDENT_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION,
    raise_err,
)
from middleware import require_roles
from response import success
from util import as_enum, as_str, body, list_response, opt, req

bp = Blueprint("incidents", __name__)

ALL_ROLES = ("Coordinator", "IntakeVolunteer", "Fixer", "SafetyOfficer")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RESOLUTION_ACTIONS = ("NONE", "WARNING", "SUSPENSION")


def get_incident_or_404(incident_id):
    rec = db.incidents.get(incident_id)
    if rec is None:
        raise_err(ERR_INCIDENT_NOT_FOUND, "SafetyIncident %s does not exist" % incident_id)
    return rec


@bp.post("/api/safety-incidents")
@require_roles("Coordinator", "Fixer", "SafetyOfficer")
def create_incident():
    b = body()
    # Existence (priority 3): body FKs in declared order.
    event_id = as_str(req(b, "event_id"), "event_id")
    if event_id not in db.events:
        raise_err(ERR_EVENT_NOT_FOUND, "RepairEvent %s does not exist" % event_id)
    item_id = opt(b, "item_id")
    if item_id is not None:
        as_str(item_id, "item_id")
        if item_id not in db.items:
            raise_err(ERR_ITEM_NOT_FOUND, "RepairItem %s does not exist" % item_id)
    fixer_id = opt(b, "fixer_id")
    if fixer_id is not None:
        as_str(fixer_id, "fixer_id")
        if fixer_id not in db.fixers:
            raise_err(ERR_FIXER_NOT_FOUND, "FixerProfile %s does not exist" % fixer_id)
    severity = as_enum(req(b, "severity"), "severity", SEVERITIES)
    description = as_str(req(b, "description"), "description")
    rec = db.stamp_new(
        {
            "event_id": event_id,
            "item_id": item_id,
            "fixer_id": fixer_id,
            "reported_by_user_id": g.user_id,
            "severity": severity,
            "description": description,
            "status": "REPORTED",
            "resolution_action": None,
        }
    )
    db.incidents[rec["id"]] = rec
    return success(ser.incident(rec), 201)


@bp.get("/api/safety-incidents")
@require_roles(*ALL_ROLES)
def list_incidents():
    return list_response(
        db.incidents.values(),
        ser.incident,
        [
            ("event_id", "event_id"),
            ("item_id", "item_id"),
            ("fixer_id", "fixer_id"),
            ("status", "status"),
        ],
    )


@bp.get("/api/safety-incidents/<incident_id>")
@require_roles(*ALL_ROLES)
def get_incident(incident_id):
    return success(ser.incident(get_incident_or_404(incident_id)), 200)


@bp.post("/api/safety-incidents/<incident_id>/resolve")
@require_roles("SafetyOfficer")
def resolve_incident(incident_id):
    incident = get_incident_or_404(incident_id)
    b = body()
    action = as_enum(req(b, "resolution_action"), "resolution_action", RESOLUTION_ACTIONS)
    if incident["status"] != "REPORTED":
        raise_err(ERR_INVALID_INCIDENT_STATE, "Only a REPORTED incident can be resolved")
    # Segregation of duties: the resolver must not be the reporter.
    if g.user_id == incident["reported_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The reporter cannot resolve this incident")
    if action == "SUSPENSION" and incident["fixer_id"] is None:
        raise_err(ERR_VALIDATION, "SUSPENSION requires the incident's fixer_id to be set")
    incident["status"] = "RESOLVED"
    incident["resolution_action"] = action
    db.touch(incident)
    if action == "SUSPENSION":
        fixer = db.fixers.get(incident["fixer_id"])
        if fixer is not None:
            services.suspend_fixer(fixer)
    return success(ser.incident(incident), 200)


@bp.post("/api/safety-incidents/<incident_id>/dismiss")
@require_roles("SafetyOfficer")
def dismiss_incident(incident_id):
    incident = get_incident_or_404(incident_id)
    if incident["status"] != "REPORTED":
        raise_err(ERR_INVALID_INCIDENT_STATE, "Only a REPORTED incident can be dismissed")
    if g.user_id == incident["reported_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The reporter cannot dismiss this incident")
    incident["status"] = "DISMISSED"
    db.touch(incident)
    return success(ser.incident(incident), 200)
