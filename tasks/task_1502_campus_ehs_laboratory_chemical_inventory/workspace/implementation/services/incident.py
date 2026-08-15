"""Incident / near-miss reporting and closure (PRD §3.6)."""
import db
from errors import ApiError, ERR_INCIDENT_STATE
from services.common import touch, refresh_posture


def validate_incident_body(body):
    """Priority 2 well-formedness for POST /ehs/incidents (before FK existence)."""
    from services.common import (require_fields, require_string, require_enum,
                                 optional_bool, SEVERITIES_INCIDENT)
    require_fields(body, ["lab_id", "title", "description", "severity"])
    require_string(body, "title")
    require_string(body, "description")
    require_enum(body, "severity", SEVERITIES_INCIDENT)
    optional_bool(body, "near_miss", default=False)


def create_incident(lab, body, user_id):
    from services.common import (require_string, require_enum, optional_bool,
                                 SEVERITIES_INCIDENT)
    incident = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "title": require_string(body, "title"),
        "description": require_string(body, "description"),
        "severity": require_enum(body, "severity", SEVERITIES_INCIDENT),
        "near_miss": optional_bool(body, "near_miss", default=False),
        "status": "REPORTED",
        "reported_by": user_id,
        "resolution": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.incidents[incident["id"]] = incident
    refresh_posture(lab)
    return incident


def close(incident, lab, resolution):
    if incident["status"] != "REPORTED":
        raise ApiError(ERR_INCIDENT_STATE, "Incident must be REPORTED to close", 409)
    incident["status"] = "CLOSED"
    incident["resolution"] = resolution
    touch(incident)
    refresh_posture(lab)
    return incident
