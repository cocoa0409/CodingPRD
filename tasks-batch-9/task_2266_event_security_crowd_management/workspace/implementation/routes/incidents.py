"""Incident endpoints (PRD 3.8)."""

from flask import Blueprint

import calc
import engine
import serial
import valid
from auth import authenticate, plain_action
from calc import num
from db import clock_iso, db, make_record, now, now_iso, touch
from errors import ApiError
from response import object_response
from routes._common import get_event, get_incident, match_filters, paginated

bp = Blueprint("incidents", __name__)

CATEGORIES = ("MEDICAL", "EJECTION", "LAW_ENFORCEMENT", "CROWD_SURGE", "PROHIBITED_ITEM")
SEVERITIES = ("MINOR", "MODERATE", "SEVERE", "CRITICAL")
STATUSES = (
    "REPORTED",
    "TRIAGED",
    "MEDICAL_HANDOFF",
    "EJECTION_IN_PROGRESS",
    "LE_HANDOFF",
    "RESOLVED",
    "CLOSED_UNFOUNDED",
)
ACTIONS = (
    "TRIAGE",
    "ESCALATE",
    "MEDICAL_HANDOFF",
    "EJECT",
    "LE_HANDOFF",
    "RESOLVE",
    "CLOSE_UNFOUNDED",
)
WRITE_ROLES = {"PostSupervisor", "IncidentCommander", "SecurityDirector"}
ACTION_ROLES = {"IncidentCommander", "SecurityDirector"}
READ_ROLES = {"SecurityDirector", "StaffingCoordinator", "IncidentCommander", "PostSupervisor"}
TRIAGE_EVENT_STATUSES = ("BRIEFED", "DOORS_OPEN", "IN_PROGRESS", "SUSPENDED")


@bp.post("/security-events/<event_id>/incidents")
def report_incident(event_id):
    actor = authenticate(WRITE_ROLES)
    payload = valid.body()
    zone_id = valid.req_string(payload, "zone_id")
    category = valid.req_enum(payload, "category", CATEGORIES)
    severity = valid.req_enum(payload, "severity", SEVERITIES)
    description = valid.req_string(payload, "description")

    event = get_event(event_id)
    zone = db.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    if zone.get("venue_id") != event.get("venue_id"):
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH", "The referenced zone does not belong to the event's venue."
        )

    record = make_record(
        {
            "event_id": event["id"],
            "zone_id": zone["id"],
            "category": category,
            "severity": severity,
            "severity_at_report": severity,
            "description": description,
            "reported_by_user_id": actor.user_id,
            "reported_at": clock_iso(),
            "triaged_at": None,
            "resolved_at": None,
            "response_minutes": None,
            "sla_breached": False,
            "handoff_agency_ref": None,
            "ejection_patron_ref": None,
            "resolution_note": None,
            "status": "REPORTED",
        }
    )
    db.incidents[record["id"]] = record
    engine.cascade_event_only(event)
    return object_response(serial.incident(record), 201)


@bp.get("/incidents/<incident_id>")
def read_incident(incident_id):
    authenticate(READ_ROLES)
    incident = get_incident(incident_id)
    return object_response(serial.incident(incident))


@bp.get("/incidents")
def list_incidents():
    authenticate(READ_ROLES)
    filters = {
        "event_id": valid.query_string("event_id"),
        "zone_id": valid.query_string("zone_id"),
        "status": valid.query_enum("status", STATUSES),
        "category": valid.query_enum("category", CATEGORIES),
        "severity": valid.query_enum("severity", SEVERITIES),
        "sla_breached": valid.query_bool("sla_breached"),
    }
    records = [i for i in db.incidents.values() if match_filters(i, filters)]
    return paginated(records, serial.incident)


def _supervisor_on_duty(event):
    plan = engine.current_plan(event["id"])
    if plan is None:
        return False
    supervisor_post_ids = set(
        post["id"] for post in engine.plan_posts(plan["id"]) if post.get("post_type") == "SUPERVISOR"
    )
    for assignment in db.assignments.values():
        if (
            assignment.get("post_id") in supervisor_post_ids
            and assignment.get("assignment_status") == "CONFIRMED"
            and assignment.get("duty_status") == "ON_POST"
        ):
            return True
    return False


def _bad_state(message):
    raise ApiError("ERR_INVALID_STATE", message)


@bp.post("/incidents/<incident_id>/actions")
def incident_actions(incident_id):
    authenticate(ACTION_ROLES)
    payload = valid.body()
    action = plain_action(payload, ACTIONS)

    requested_severity = None
    handoff_agency_ref = None
    ejection_patron_ref = None
    resolution_note = None
    if action == "ESCALATE":
        requested_severity = valid.req_enum(payload, "severity", SEVERITIES)
    elif action in ("MEDICAL_HANDOFF", "LE_HANDOFF"):
        handoff_agency_ref = valid.req_string(payload, "handoff_agency_ref")
    elif action == "EJECT":
        ejection_patron_ref = valid.req_string(payload, "ejection_patron_ref")
    elif action in ("RESOLVE", "CLOSE_UNFOUNDED"):
        resolution_note = valid.req_string(payload, "resolution_note")

    incident = get_incident(incident_id)
    event = db.events.get(incident.get("event_id"))
    status = incident.get("status")

    if action == "TRIAGE":
        if status != "REPORTED":
            _bad_state("Only a REPORTED incident may be triaged.")
        if event is None or event.get("status") not in TRIAGE_EVENT_STATUSES:
            _bad_state("The event is not in an operational state for triage.")
        incident["status"] = "TRIAGED"
        incident["triaged_at"] = clock_iso()
        response_minutes, breached = calc.incident_response_metrics(
            engine.dt(incident, "reported_at"),
            engine.dt(incident, "triaged_at"),
            incident.get("severity_at_report"),
        )
        incident["response_minutes"] = num(response_minutes)
        incident["sla_breached"] = breached
        touch(incident)
        engine.cascade_event_only(event)

    elif action == "ESCALATE":
        if status not in ("REPORTED", "TRIAGED"):
            _bad_state("Only a REPORTED or TRIAGED incident may be escalated.")
        current = incident.get("severity")
        if calc.SEVERITY_RANK[requested_severity] <= calc.SEVERITY_RANK[current]:
            raise ApiError("ERR_SEVERITY_NOT_ESCALATING")
        incident["severity"] = requested_severity
        touch(incident)
        engine.cascade_event_only(event)

    elif action == "MEDICAL_HANDOFF":
        if status != "TRIAGED":
            _bad_state("Only a TRIAGED incident may be handed to a medical agency.")
        if incident.get("category") != "MEDICAL":
            _bad_state("A medical handoff requires a MEDICAL incident.")
        incident["status"] = "MEDICAL_HANDOFF"
        incident["handoff_agency_ref"] = handoff_agency_ref
        touch(incident)

    elif action == "EJECT":
        if status != "TRIAGED":
            _bad_state("Only a TRIAGED incident may proceed to ejection.")
        if incident.get("category") not in ("EJECTION", "PROHIBITED_ITEM"):
            _bad_state("An ejection requires an EJECTION or PROHIBITED_ITEM incident.")
        if event is None or not _supervisor_on_duty(event):
            raise ApiError("ERR_NO_SUPERVISOR_ON_DUTY")
        incident["status"] = "EJECTION_IN_PROGRESS"
        incident["ejection_patron_ref"] = ejection_patron_ref
        touch(incident)

    elif action == "LE_HANDOFF":
        if status != "TRIAGED":
            _bad_state("Only a TRIAGED incident may be handed to law enforcement.")
        if incident.get("category") != "LAW_ENFORCEMENT" and incident.get("severity") not in (
            "SEVERE",
            "CRITICAL",
        ):
            _bad_state(
                "A law-enforcement handoff requires a LAW_ENFORCEMENT category or a "
                "SEVERE/CRITICAL severity."
            )
        if event is None or not _supervisor_on_duty(event):
            raise ApiError("ERR_NO_SUPERVISOR_ON_DUTY")
        incident["status"] = "LE_HANDOFF"
        incident["handoff_agency_ref"] = handoff_agency_ref
        touch(incident)
        if incident.get("severity") == "CRITICAL" and event is not None:
            event["ingress_status"] = "HOLD"
            engine.hold_open_lanes(event)
            engine.recompute_event(event)
            touch(event)
        else:
            engine.cascade_event_only(event)

    elif action == "RESOLVE":
        if status not in ("TRIAGED", "MEDICAL_HANDOFF", "EJECTION_IN_PROGRESS", "LE_HANDOFF"):
            _bad_state("This incident may not be resolved from '%s'." % status)
        from_le = status == "LE_HANDOFF"
        incident["status"] = "RESOLVED"
        incident["resolved_at"] = clock_iso()
        incident["resolution_note"] = resolution_note
        touch(incident)
        if event is not None:
            if from_le and engine.open_critical_incident_count(event["id"]) == 0:
                if event.get("ingress_status") != "NORMAL":
                    event["ingress_status"] = "NORMAL"
                engine.release_held_lanes(event)
                engine.recompute_event(event)
                touch(event)
            else:
                engine.cascade_event_only(event)

    else:  # CLOSE_UNFOUNDED
        if status != "REPORTED":
            _bad_state("Only a REPORTED incident may be closed as unfounded.")
        incident["status"] = "CLOSED_UNFOUNDED"
        incident["resolved_at"] = clock_iso()
        incident["resolution_note"] = resolution_note
        touch(incident)
        engine.cascade_event_only(event)

    return object_response(serial.incident(incident))
