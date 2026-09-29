"""Interagency consultation and agency capacity (PRD 3.6)."""

from flask import Blueprint, g

import db
import response
import validation as v
from errors import ApiError, fail, invalid
from middleware import endpoint
from routes.helpers import body_ref, list_response, path_row
from services import calc, rollups

bp = Blueprint("consultations", __name__)

CONSULTATION_TYPES = (
    "ESA_SECTION_7",
    "NHPA_SECTION_106",
    "CWA_SECTION_404",
    "COOPERATING_AGENCY",
)

CONSULTATION_SPEC = {
    "action_id": {"required": True, "check": v.c_str(1)},
    "agency_id": {"required": True, "check": v.c_str(1)},
    "consultation_type": {"required": True, "check": v.c_enum(CONSULTATION_TYPES)},
    "requested_start_at": {"required": True, "check": v.c_datetime},
}

AGENCY_OUTCOMES = ("CONCURRED", "CONDITIONAL_CONCURRENCE", "NOT_CONCURRED")

READ_ROLES = ["NepaCoordinator", "AgencyLiaison", "ReviewingOfficial", "DecidingOfficial"]


@endpoint(bp, "/consultations", ["POST"], ["NepaCoordinator"])
def create_consultation():
    body = v.parse_body(CONSULTATION_SPEC)
    action = body_ref("actions", body["action_id"], "action_id")
    agency = body_ref("agencies", body["agency_id"], "agency_id")

    if agency["status"] == "SUSPENDED":
        fail("ERR_AGENCY_SUSPENDED", "a SUSPENDED agency may not receive consultation requests")

    start = db.parse_dt(body["requested_start_at"])
    due = db.add_days(start, agency["statutory_response_days"])
    candidate_end = db.add_days(due, agency["handoff_buffer_days"])

    colliding = 0
    for other in db.rows("consultations"):
        if other["agency_id"] != agency["id"] or other["status"] != "PENDING":
            continue
        other_start, other_end = calc.occupied_interval(other, agency)
        # Closed intervals on both ends: a single shared instant collides.
        if start <= other_end and other_start <= candidate_end:
            colliding += 1
    if colliding >= agency["max_concurrent_consultations"]:
        fail(
            "ERR_AGENCY_CAPACITY_EXCEEDED",
            "the agency already carries %d overlapping pending consultations" % colliding,
        )

    required = calc.required_consultation_types(action)
    row = db.new_row(
        "consultations",
        {
            "action_id": action["id"],
            "agency_id": agency["id"],
            "consultation_type": body["consultation_type"],
            "requested_start_at": body["requested_start_at"],
            "statutory_due_at": db.iso(due),
            "is_required": body["consultation_type"] in required,
            "responded_at": None,
            "late": False,
            "conditions_text": None,
            "status": "PENDING",
        },
    )
    rollups.refresh_agency(agency)
    return response.created(db.public(row))


@endpoint(bp, "/consultations/<consultation_id>", ["GET"], READ_ROLES)
def get_consultation(consultation_id):
    consultation = path_row("consultations", consultation_id, "consultation request")
    return response.ok(db.public(consultation))


@endpoint(bp, "/consultations", ["GET"], READ_ROLES)
def list_consultations():
    return list_response(
        db.rows("consultations"), "action_id", "agency_id", "status", "consultation_type"
    )


@endpoint(bp, "/consultations/<consultation_id>/respond", ["POST"], [
    "AgencyLiaison",
    "NepaCoordinator",
])
def respond_consultation(consultation_id):
    body = v.parse_body(
        {
            "outcome": {
                "required": True,
                "check": v.c_enum(AGENCY_OUTCOMES + ("WITHDRAWN",)),
            },
            "conditions_text": {"check": v.c_str(0), "default": None},
        }
    )
    outcome = body["outcome"]
    if outcome == "CONDITIONAL_CONCURRENCE":
        text = body["conditions_text"]
        if text is None or not text.strip():
            raise invalid("conditions_text is required for a CONDITIONAL_CONCURRENCE outcome")

    consultation = path_row("consultations", consultation_id, "consultation request")

    if g.role == "AgencyLiaison" and outcome == "WITHDRAWN":
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "WITHDRAWN is the coordinator's own retraction",
            403,
        )
    if g.role == "NepaCoordinator" and outcome != "WITHDRAWN":
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "an agency outcome may only be recorded by the AgencyLiaison",
            403,
        )
    if g.role == "AgencyLiaison" and consultation["agency_id"] != g.user_id:
        raise ApiError(
            "ERR_AGENCY_SCOPE_VIOLATION",
            "the consultation belongs to a different agency",
            403,
        )

    if consultation["status"] != "PENDING":
        fail("ERR_INVALID_STATE", "only a PENDING consultation may be answered")

    now = db.logical_now()
    consultation["responded_at"] = db.iso(now)
    if outcome == "WITHDRAWN":
        consultation["late"] = False
    else:
        consultation["late"] = now > db.parse_dt(consultation["statutory_due_at"])
    if outcome == "CONDITIONAL_CONCURRENCE":
        consultation["conditions_text"] = body["conditions_text"]
    consultation["status"] = outcome
    db.touch(consultation)

    agency = db.find("agencies", consultation["agency_id"])
    rollups.refresh_agency(agency)
    return response.ok(db.public(consultation))
