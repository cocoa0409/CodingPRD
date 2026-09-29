"""SecurityIncident endpoints: proctoring incidents and score holds (PRD 3.9)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, touch
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_EXAM_OPERATIONS,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    opt_str,
    peek_body,
    req_enum,
    req_str,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import cascades, derive, lookup

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = ("PROHIBITED_DEVICE", "IMPERSONATION", "CONTENT_DISCLOSURE",
                  "PROCTOR_INTERRUPTION")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
ADJUDICATIONS = ("SUBSTANTIATE", "DISMISS")
HOLDABLE_SCORE_STATUSES = ("PENDING", "SCORED")


@bp.post("/exam-registrations/<registration_id>/security-incidents")
@api
def open_incident(registration_id):
    authenticate([ROLE_EXAM_OPERATIONS])
    registration = lookup.registration(registration_id)
    body = ensure_body(peek_body())
    incident_type = req_enum(body, "incident_type", INCIDENT_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")

    incident = new_record(
        registration_id=registration["id"],
        incident_type=incident_type,
        severity=severity,
        description=description,
        status="OPEN",
        outcome_note=None,
        placed_hold=False,
    )
    mark_created(incident)
    DB.incidents[incident["id"]] = incident

    # A CRITICAL incident freezes the score dimension immediately; seat_status is
    # untouched, so a candidate mid-sitting is not ejected by the paperwork.
    if severity == "CRITICAL" and registration["score_status"] in HOLDABLE_SCORE_STATUSES:
        registration["score_status_before_hold"] = registration["score_status"]
        registration["score_status"] = "WITHHELD"
        touch(registration)
        incident["placed_hold"] = True

    return created_response(serialize.incident(incident))


@bp.get("/exam-registrations/<registration_id>/security-incidents")
@api
def list_registration_incidents(registration_id):
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_PROGRAM_ADMIN])
    registration = lookup.registration(registration_id)
    limit, offset = read_pagination()
    rows = derive.incidents_of_registration(registration["id"])
    rows = apply_filters(rows, {
        "status": "status",
        "severity": "severity",
        "incident_type": "incident_type",
    })
    return paginate(rows, serialize.incident, limit, offset)


@bp.get("/security-incidents/<incident_id>")
@api
def read_incident(incident_id):
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_PROGRAM_ADMIN])
    return object_response(serialize.incident(lookup.incident(incident_id)))


@bp.post("/security-incidents/<incident_id>/adjudicate")
@api
def adjudicate_incident(incident_id):
    authenticate([ROLE_EXAM_OPERATIONS])
    incident = lookup.incident(incident_id)
    body = ensure_body(peek_body())
    outcome = req_enum(body, "outcome", ADJUDICATIONS)
    outcome_note = opt_str(body, "outcome_note")

    # Layer 12: adjudication is available only while the incident is OPEN.
    if incident["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")

    registration = DB.registrations[incident["registration_id"]]
    if outcome_note is not None:
        incident["outcome_note"] = outcome_note

    if outcome == "SUBSTANTIATE":
        incident["status"] = "SUBSTANTIATED"
        touch(incident)
        cascades.cascade_incident_substantiated(incident, registration)
    else:
        incident["status"] = "UNSUBSTANTIATED"
        touch(incident)
        if incident["placed_hold"]:
            registration["score_status"] = registration["score_status_before_hold"]
            registration["score_status_before_hold"] = None
            touch(registration)

    return object_response(serialize.incident(incident))
