"""Incident endpoints: raise (with the depth-3 trip cascade), acknowledge,
mitigate, close (PRD 3.9)."""
from flask import Blueprint, request

import resolve
import store
from auth import authenticate, authorize
from errors import (
    raise_err,
    ERR_INCIDENT_NOT_CLOSABLE,
    ERR_INVALID_STATE,
    ERR_REFERENCED_NOT_FOUND,
    ERR_RESOLUTION_NOTES_REQUIRED,
)
from services import (
    INCIDENT_KINDS,
    SEVERITIES,
    TRIP_KINDS,
    TRIP_SEVERITIES,
    create_incident_record,
    incident_json,
    incidents_of,
    require_active_operator,
    set_posture,
    trip_boiler,
)
from util import (
    body_json,
    list_response,
    opt_str,
    req_dt,
    req_enum,
    req_str,
    success_object,
    touch,
)

bp = Blueprint("incidents", __name__)

READERS = ["PlantManager", "Operator"]


@bp.post("/plants/<plantId>/incidents")
def create_incident(plantId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    body = body_json()
    raised_by = req_str(body, "raised_by_operator_id")
    severity = req_enum(body, "severity", SEVERITIES)
    kind = req_enum(body, "kind", INCIDENT_KINDS)
    triggered_boiler_id = opt_str(body, "triggered_boiler_id")
    raised_at = req_dt(body, "raised_at")
    # referential integrity(11)
    if store.operators.get(raised_by) is None:
        raise_err(ERR_REFERENCED_NOT_FOUND,
                  "raised_by_operator_id does not reference an existing operator")
    boiler = None
    if triggered_boiler_id is not None:
        boiler = store.boilers.get(triggered_boiler_id)
        if boiler is None or boiler["plant_id"] != plant["id"]:
            raise_err(ERR_REFERENCED_NOT_FOUND,
                      "triggered_boiler_id does not reference an existing boiler")
    rec = create_incident_record(
        plant,
        severity=severity,
        kind=kind,
        triggered_boiler_id=triggered_boiler_id,
        raised_by=raised_by,
        raised_at=raised_at,
    )
    # depth-1 trip (+ cert suspension for RELIEF_VALVE_LIFT), then depth 2/3
    if (severity in TRIP_SEVERITIES and kind in TRIP_KINDS and boiler is not None):
        trip_boiler(plant, boiler, suspend_cert=(kind == "RELIEF_VALVE_LIFT"))
    if set_posture(plant):
        touch(plant)
    return success_object(incident_json(rec), 201)


@bp.get("/plants/<plantId>/incidents/<incidentId>")
def get_incident(plantId, incidentId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    rec = resolve.incident(plant, incidentId)
    return success_object(incident_json(rec))


@bp.get("/plants/<plantId>/incidents")
def list_incidents(plantId):
    _, role = authenticate()
    authorize(role, READERS)
    plant = resolve.plant(plantId)
    recs = incidents_of(plant["id"])
    status = request.args.get("status")
    severity = request.args.get("severity")
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    if severity is not None:
        recs = [i for i in recs if i["severity"] == severity]
    return list_response(recs, incident_json)


@bp.post("/plants/<plantId>/incidents/<incidentId>/acknowledge")
def acknowledge_incident(plantId, incidentId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    rec = resolve.incident(plant, incidentId)
    # state(4)
    if rec["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN incident can be acknowledged")
    # license(8)
    require_active_operator(uid)
    rec["status"] = "ACKNOWLEDGED"
    touch(rec)
    return success_object(incident_json(rec))


@bp.post("/plants/<plantId>/incidents/<incidentId>/mitigate")
def mitigate_incident(plantId, incidentId):
    uid, role = authenticate()
    authorize(role, ["Operator"])
    plant = resolve.plant(plantId)
    rec = resolve.incident(plant, incidentId)
    # state(4)
    if rec["status"] != "ACKNOWLEDGED":
        raise_err(ERR_INVALID_STATE, "Only an ACKNOWLEDGED incident can be mitigated")
    # license(8)
    require_active_operator(uid)
    rec["status"] = "MITIGATED"
    touch(rec)
    # mitigation releases the posture gate (PRD 3.9)
    if set_posture(plant):
        touch(plant)
    return success_object(incident_json(rec))


@bp.post("/plants/<plantId>/incidents/<incidentId>/close")
def close_incident(plantId, incidentId):
    _, role = authenticate()
    authorize(role, ["PlantManager"])
    plant = resolve.plant(plantId)
    rec = resolve.incident(plant, incidentId)
    # state(4): OPEN or MITIGATED only
    if rec["status"] not in ("OPEN", "MITIGATED"):
        raise_err(ERR_INVALID_STATE, "Only an OPEN or MITIGATED incident can be closed")
    body = body_json()
    notes = body.get("resolution_notes")
    # notes gate(20)
    if not isinstance(notes, str) or not notes.strip():
        raise_err(ERR_RESOLUTION_NOTES_REQUIRED,
                  "resolution_notes must be non-empty to close an incident")
    # closure path(21): from OPEN only LOW may close directly
    if rec["status"] == "OPEN" and rec["severity"] != "LOW":
        raise_err(ERR_INCIDENT_NOT_CLOSABLE,
                  "Non-LOW incidents must traverse ACKNOWLEDGED and MITIGATED before closure")
    rec["resolution_notes"] = notes
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(incident_json(rec))
