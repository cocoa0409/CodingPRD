"""AfterActionReview endpoints (PRD 3.9)."""

from flask import Blueprint

import engine
import serial
import valid
from auth import authenticate, check_action_authority, require_action
from db import db, make_record, touch
from errors import ApiError
from response import object_response
from routes._common import get_event, get_review, match_filters, paginated

bp = Blueprint("reviews", __name__)

REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "FINALIZED")
WRITE_ROLES = {"IncidentCommander", "SecurityDirector"}
LIST_ROLES = {"SecurityDirector", "IncidentCommander", "StaffingCoordinator", "RiskAnalyst"}


@bp.post("/security-events/<event_id>/after-action-reviews")
def create_review(event_id):
    actor = authenticate(WRITE_ROLES)
    payload = valid.body()
    narrative = valid.req_string(payload, "narrative")
    corrective_action_count = valid.req_int(payload, "corrective_action_count", minimum=0)

    event = get_event(event_id)

    for existing in db.reviews.values():
        if existing.get("event_id") == event["id"] and existing.get("status") != "FINALIZED":
            raise ApiError("ERR_REVIEW_ALREADY_EXISTS")

    record = make_record(
        {
            "event_id": event["id"],
            "narrative": narrative,
            "corrective_action_count": corrective_action_count,
            "authored_by_user_id": actor.user_id,
            "finalized_by_user_id": None,
            "return_reason": None,
            "total_incident_count": 0,
            "sla_breach_count": 0,
            "peak_density_level": "GREEN",
            "no_show_rate": 0,
            "coverage_shortfall_minutes": 0,
            "status": "DRAFT",
        }
    )
    db.reviews[record["id"]] = record
    return object_response(serial.review(record), 201)


@bp.get("/security-events/<event_id>/after-action-reviews")
def list_reviews(event_id):
    authenticate(LIST_ROLES)
    filters = {"status": valid.query_enum("status", REVIEW_STATUSES)}
    event = get_event(event_id)
    records = [
        r
        for r in db.reviews.values()
        if r.get("event_id") == event["id"] and match_filters(r, filters)
    ]
    return paginated(records, serial.review)


@bp.post("/after-action-reviews/<review_id>/decision")
def review_decision(review_id):
    actor = authenticate(WRITE_ROLES)
    payload = valid.body()
    action = require_action(payload, "review_decision")
    check_action_authority(actor, "review_decision", action)

    return_reason = None
    if action == "RETURN":
        return_reason = valid.req_string(payload, "return_reason")

    review = get_review(review_id)
    event = db.events.get(review.get("event_id"))
    status = review.get("status")

    if action == "SUBMIT":
        if status != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Only a DRAFT review may be submitted.")
        if event is None or event.get("status") != "CLOSED":
            raise ApiError("ERR_INVALID_STATE", "The event is not CLOSED.")
        for incident in engine.event_incidents(event["id"]):
            if incident.get("status") not in ("RESOLVED", "CLOSED_UNFOUNDED"):
                raise ApiError("ERR_INVALID_STATE", "An incident on the event is still open.")
        review["status"] = "SUBMITTED"
        engine.after_action_metrics(review, event)
        touch(review)

    elif action == "REVISE":
        if status != "RETURNED":
            raise ApiError("ERR_INVALID_STATE", "Only a RETURNED review may be revised.")
        review["status"] = "DRAFT"
        review["return_reason"] = None
        touch(review)

    elif action == "RETURN":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED review may be returned.")
        if actor.user_id == review.get("authored_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        review["status"] = "RETURNED"
        review["return_reason"] = return_reason
        touch(review)

    else:  # FINALIZE
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED review may be finalized.")
        if actor.user_id == review.get("authored_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        review["status"] = "FINALIZED"
        review["finalized_by_user_id"] = actor.user_id
        if event is not None:
            engine.after_action_metrics(review, event)
        touch(review)
        if event is not None and event.get("status") == "CLOSED":
            event["status"] = "DEBRIEFED"
            engine.recompute_event(event)
            touch(event)

    return object_response(serial.review(review))
