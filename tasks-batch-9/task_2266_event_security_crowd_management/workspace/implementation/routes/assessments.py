"""RiskAssessment endpoints (PRD 3.2, 3.3)."""

from flask import Blueprint

import calc
import engine
import serial
import valid
from auth import authenticate, check_action_authority, require_action
from calc import num
from db import db, make_record, sorted_records, touch
from errors import ApiError
from response import object_response
from routes._common import get_assessment, get_event, match_filters, paginated

bp = Blueprint("assessments", __name__)

THREAT_LEVELS = ("LOW", "GUARDED", "ELEVATED", "HIGH", "SEVERE")
PROTEST_LIKELIHOODS = ("NONE", "POSSIBLE", "LIKELY")
CROWD_PROFILES = ("SEATED", "FAMILY", "GENERAL_ADMISSION", "MOSH_PIT")
ASSESSMENT_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")

AUTHOR_ROLES = {"RiskAnalyst", "SecurityDirector"}
READ_ROLES = {"SecurityDirector", "RiskAnalyst", "StaffingCoordinator"}

DERIVED_FIELDS = (
    "score_basis_attendance",
    "composite_threat_score",
    "risk_tier",
    "required_perimeter_guards",
    "required_ingress_guards",
    "required_floor_guards",
    "required_exit_guards",
    "required_line_guards",
    "required_supervisors",
    "required_total_staff",
    "required_screening_lanes",
    "minimum_staffing_cost_floor_cents",
)


def _recompute_block(assessment, event, basis_attendance):
    venue = db.venues.get(event["venue_id"]) or {}
    score = calc.composite_threat_score(
        basis_attendance,
        venue.get("gross_capacity") or 1,
        assessment["threat_level_input"],
        assessment["protest_likelihood"],
        assessment["crowd_profile"],
        assessment["layout_complexity_score"],
        event.get("alcohol_served"),
        event.get("vip_present"),
        assessment["history_incident_rate"],
    )
    tier = calc.risk_tier(score)
    matrix = calc.required_staff_matrix(basis_attendance, tier, venue.get("door_count") or 1)
    span = calc.supervisor_span(matrix["required_line_guards"])
    assessment["score_basis_attendance"] = basis_attendance
    assessment["composite_threat_score"] = num(score)
    assessment["risk_tier"] = tier
    assessment.update(matrix)
    assessment.update(span)
    assessment["required_screening_lanes"] = calc.required_screening_lanes(basis_attendance)
    assessment["minimum_staffing_cost_floor_cents"] = calc.minimum_staffing_cost_floor_cents(
        span["required_total_staff"]
    )


@bp.post("/security-events/<event_id>/risk-assessments")
def create_assessment(event_id):
    authenticate(AUTHOR_ROLES)
    payload = valid.body()
    threat_level_input = valid.req_enum(payload, "threat_level_input", THREAT_LEVELS)
    protest_likelihood = valid.req_enum(payload, "protest_likelihood", PROTEST_LIKELIHOODS)
    crowd_profile = valid.req_enum(payload, "crowd_profile", CROWD_PROFILES)
    ingress_door_count = valid.req_int(payload, "ingress_door_count", minimum=1)
    layout_complexity_score = valid.req_int(payload, "layout_complexity_score", minimum=1, maximum=5)
    history_incident_rate = valid.req_number(
        payload, "history_incident_rate", minimum=0, maximum=25, places=2
    )

    event = get_event(event_id)

    record = make_record(
        {
            "event_id": event["id"],
            "revision_number": 1,
            "threat_level_input": threat_level_input,
            "protest_likelihood": protest_likelihood,
            "crowd_profile": crowd_profile,
            "ingress_door_count": ingress_door_count,
            "layout_complexity_score": layout_complexity_score,
            "history_incident_rate": num(history_incident_rate),
            "attendance_basis": "EXPECTED",
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "rejection_reason": None,
        }
    )
    for field in DERIVED_FIELDS:
        record[field] = None
    db.assessments[record["id"]] = record
    return object_response(serial.assessment(record), 201)


@bp.get("/security-events/<event_id>/risk-assessments")
def list_event_assessments(event_id):
    authenticate(READ_ROLES)
    filters = {"status": valid.query_enum("status", ASSESSMENT_STATUSES)}
    event = get_event(event_id)
    records = [
        a
        for a in db.assessments.values()
        if a.get("event_id") == event["id"] and match_filters(a, filters)
    ]
    return paginated(records, serial.assessment)


@bp.get("/risk-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authenticate(READ_ROLES)
    assessment = get_assessment(assessment_id)
    return object_response(serial.assessment(assessment))


@bp.post("/risk-assessments/<assessment_id>/decision")
def assessment_decision(assessment_id):
    actor = authenticate(AUTHOR_ROLES)
    payload = valid.body()
    action = require_action(payload, "risk_decision")
    check_action_authority(actor, "risk_decision", action)
    rejection_reason = None
    if action == "REJECT":
        rejection_reason = valid.req_string(payload, "rejection_reason")

    assessment = get_assessment(assessment_id)
    event = db.events.get(assessment["event_id"])

    if action == "SUBMIT":
        if assessment["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Only a DRAFT assessment may be submitted.")
        if event is None or event.get("status") not in ("PLANNING", "RISK_ASSESSED"):
            raise ApiError("ERR_INVALID_STATE", "The event has moved past risk assessment.")
        if event.get("gate_posture") == "FROZEN":
            raise ApiError("ERR_EVENT_GATE_FROZEN")
        assessment["status"] = "SUBMITTED"
        assessment["attendance_basis"] = "EXPECTED"
        assessment["submitted_by_user_id"] = actor.user_id
        _recompute_block(assessment, event, event["expected_attendance"])
        touch(assessment)

    elif action == "APPROVE":
        if assessment["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED assessment may be approved.")
        if event is None or event.get("status") not in ("PLANNING", "RISK_ASSESSED"):
            raise ApiError("ERR_INVALID_STATE", "The event has moved past risk assessment.")
        if actor.user_id == assessment.get("submitted_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        ticketed = event.get("ticketed_attendance")
        if ticketed is not None:
            assessment["attendance_basis"] = "TICKETED"
            basis = ticketed
        else:
            assessment["attendance_basis"] = "EXPECTED"
            basis = event["expected_attendance"]
        assessment["status"] = "APPROVED"
        assessment["approved_by_user_id"] = actor.user_id
        _recompute_block(assessment, event, basis)
        touch(assessment)
        for other in sorted_records(list(db.assessments.values())):
            if (
                other["id"] != assessment["id"]
                and other.get("event_id") == event["id"]
                and other.get("status") == "APPROVED"
            ):
                other["status"] = "SUPERSEDED"
                touch(other)
        if event.get("status") == "PLANNING":
            event["status"] = "RISK_ASSESSED"
            engine.recompute_event(event)
            touch(event)
        else:
            engine.cascade_event_only(event)

    elif action == "REJECT":
        if assessment["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED assessment may be rejected.")
        if actor.user_id == assessment.get("submitted_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        assessment["status"] = "REJECTED"
        assessment["rejection_reason"] = rejection_reason
        touch(assessment)

    else:  # REVISE
        if assessment["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE", "Only a REJECTED assessment may be revised.")
        assessment["status"] = "DRAFT"
        assessment["revision_number"] = (assessment.get("revision_number") or 1) + 1
        assessment["submitted_by_user_id"] = None
        assessment["rejection_reason"] = None
        touch(assessment)

    return object_response(serial.assessment(assessment))
