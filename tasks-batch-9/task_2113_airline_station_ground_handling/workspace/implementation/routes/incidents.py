from flask import Blueprint

import constants as C
import validators as V
from auth import authorize, current_user
from domain import (
    apply_changes, audit_score, plus_minutes, quarantine_gse, recompute_station_posture,
    serialize_incident, set_service_hold,
)
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import as_dt, db, new_record, ordered, require

bp = Blueprint("incidents", __name__)

REPORT_ROLES = [C.ROLE_DUTY_OFFICER, C.ROLE_SAFETY_OFFICER, C.ROLE_STATION_MANAGER]


@bp.post("/incidents")
def create_incident():
    authorize(REPORT_ROLES)
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    incident_type = V.req_enum(payload, "incident_type", C.INCIDENT_TYPES)
    severity = V.req_enum(payload, "severity", C.SEVERITIES)
    occurred_at = V.req_datetime(payload, "occurred_at")
    turn_id = V.opt_string(payload, "turn_id")
    gse_unit_id = V.opt_string(payload, "gse_unit_id")
    agent_id = V.opt_string(payload, "agent_id")
    description = V.opt_string(payload, "description")
    if as_dt(occurred_at) > db.clock:
        raise ApiError("ERR_INVALID_REQUEST", "occurred_at may not be after the logical clock.")

    station = require(db.stations, station_id, "Station")
    turn = require(db.turns, turn_id, "Turn") if turn_id else None
    unit = require(db.gse_units, gse_unit_id, "GseUnit") if gse_unit_id else None
    agent = require(db.agents, agent_id, "Agent") if agent_id else None

    for linked in (turn, unit, agent):
        if linked is not None and linked["station_id"] != station["id"]:
            raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    incident = new_record("Incident", {
        "station_id": station["id"],
        "turn_id": turn["id"] if turn else None,
        "gse_unit_id": unit["id"] if unit else None,
        "agent_id": agent["id"] if agent else None,
        "subcontractor_id": agent["subcontractor_id"] if agent else None,
        "incident_type": incident_type,
        "severity": severity,
        "occurred_at": occurred_at,
        "description": description,
        "status": "REPORTED",
        "reported_by_user_id": current_user(),
        "investigator_user_id": None,
        "findings_issued_by_user_id": None,
        "closed_by_user_id": None,
        "root_cause_code": None,
        "liability_party": None,
        "assessed_damage_cents": None,
        "reopen_count": 0,
    })
    db.incidents[incident["id"]] = incident

    recompute_station_posture(station)

    if severity == "CRITICAL" and unit is not None:
        quarantine_gse(unit)

    return respond_object(serialize_incident(incident), 201)


@bp.get("/incidents/<incident_id>")
def read_incident(incident_id):
    authorize(C.ALL_ROLES)
    incident = require(db.incidents, incident_id, "Incident")
    return respond_object(serialize_incident(incident))


@bp.get("/incidents")
def list_incidents():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.incidents.values(), {
        "station_id": "station_id",
        "turn_id": "turn_id",
        "gse_unit_id": "gse_unit_id",
        "agent_id": "agent_id",
        "subcontractor_id": "subcontractor_id",
        "status": "status",
        "severity": "severity",
    })
    return paginate(ordered(records), serialize_incident)


@bp.post("/incidents/<incident_id>/transitions")
def incident_transition(incident_id):
    authorize([C.ROLE_SAFETY_OFFICER])
    incident = require(db.incidents, incident_id, "Incident")
    payload = V.body()
    action = V.req_enum(payload, "action", C.INCIDENT_ACTIONS)
    root_cause_code = V.opt_string(payload, "root_cause_code")
    liability_party = V.opt_enum(payload, "liability_party", C.LIABILITY_PARTIES)
    assessed_damage_cents = V.opt_int(payload, "assessed_damage_cents", None, 0)
    V.opt_string(payload, "note")

    if action == "ISSUE_FINDINGS":
        if root_cause_code is None or not root_cause_code.strip():
            raise ApiError("ERR_INVALID_REQUEST", "root_cause_code is required.")
        if liability_party is None:
            raise ApiError("ERR_INVALID_REQUEST", "liability_party is required.")
        if incident["incident_type"] in C.DAMAGE_INCIDENT_TYPES and assessed_damage_cents is None:
            raise ApiError("ERR_INVALID_REQUEST", "assessed_damage_cents is required.")

    # ---- step 9: segregation of duties -----------------------------------
    actor = current_user()
    if action == "INVESTIGATE" and actor == incident["reported_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if action == "CLOSE" and incident["findings_issued_by_user_id"] is not None \
            and actor == incident["findings_issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    station = db.stations[incident["station_id"]]
    status = incident["status"]

    if action == "INVESTIGATE":
        if status not in ("REPORTED", "REOPENED"):
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(incident, {
            "status": "UNDER_INVESTIGATION",
            "investigator_user_id": actor,
        })
        recompute_station_posture(station)
    elif action == "ISSUE_FINDINGS":
        if status != "UNDER_INVESTIGATION":
            raise ApiError("ERR_INVALID_STATE")
        changes = {
            "status": "FINDINGS_ISSUED",
            "root_cause_code": root_cause_code,
            "liability_party": liability_party,
            "findings_issued_by_user_id": actor,
        }
        if assessed_damage_cents is not None:
            changes["assessed_damage_cents"] = assessed_damage_cents
        apply_changes(incident, changes)
        recompute_station_posture(station)
    elif action == "CLOSE":
        if status != "FINDINGS_ISSUED":
            raise ApiError("ERR_INVALID_STATE")
        apply_changes(incident, {"status": "CLOSED", "closed_by_user_id": actor})
        recompute_station_posture(station)
        if incident["gse_unit_id"]:
            unit = db.gse_units.get(incident["gse_unit_id"])
            if unit is not None and unit["status"] == "QUARANTINED":
                apply_changes(unit, {"status": "IN_MAINTENANCE"})
                set_service_hold(unit, db.clock, plus_minutes(db.clock, C.SERVICE_HOLD_MINUTES))
        if incident["subcontractor_id"]:
            sub = db.subcontractors.get(incident["subcontractor_id"])
            if sub is not None:
                if audit_score(sub) < C.AUTO_PROBATION_THRESHOLD and sub["status"] == "APPROVED":
                    apply_changes(sub, {"status": "PROBATION"})
    else:  # REOPEN
        if status != "CLOSED":
            raise ApiError("ERR_INVALID_STATE")
        if incident["reopen_count"] >= 2:
            raise ApiError("ERR_REOPEN_LIMIT_REACHED")
        apply_changes(incident, {
            "status": "REOPENED",
            "reopen_count": incident["reopen_count"] + 1,
        })
        recompute_station_posture(station)

    return respond_object(serialize_incident(incident))
