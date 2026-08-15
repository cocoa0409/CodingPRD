"""FeedbackSurvey endpoints (immutable; id + created_at only)."""
import uuid

from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_SURVEY_NOT_FOUND,
    ERR_REGISTRATION_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_ONE_SURVEY_PER_REGISTRATION,
    ERR_SURVEY_NOT_ELIGIBLE,
    ERR_VALIDATION,
)
from middleware import authenticate, body
from response import success_object, success_list
from services.cascades import refresh_partner_reputation
from services.core import ser_survey, sort_entities
from validate import req_string, req_int, req_bool, opt_string, check_range

bp = Blueprint("surveys", __name__)


@bp.post("/feedback-surveys")
def create_survey():
    uid, _, _ = authenticate(["EmployeeVolunteer"])
    data = body()
    registration_id = req_string(data, "registration_id")
    rating = req_int(data, "rating")
    would_repeat = req_bool(data, "would_repeat")
    comments = opt_string(data, "comments", "")
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise_err(ERR_REGISTRATION_NOT_FOUND, "registration not found")
    # ownership (step 2)
    if reg["volunteer_id"] != uid:
        raise_err(ERR_FORBIDDEN_ROLE, "volunteers may only survey their own registrations")
    # capacity/uniqueness + range (step 11)
    check_range(1 <= rating <= 5, "rating must be between 1 and 5")
    for s in db.surveys.values():
        if s["registration_id"] == reg["id"]:
            raise_err(ERR_ONE_SURVEY_PER_REGISTRATION, "a survey already exists for this registration")
    # eligibility (step 12)
    ev = db.events.get(reg["event_id"])
    if reg["rsvp_status"] != "CHECKED_IN" or ev is None or ev["status"] not in ("COMPLETED", "CLOSED"):
        raise_err(ERR_SURVEY_NOT_ELIGIBLE, "registration must be CHECKED_IN and the event COMPLETED or CLOSED")
    s = {
        "id": str(uuid.uuid4()),
        "_created": db.now(),
        "_seq": db.next_seq(),
        "registration_id": reg["id"],
        "rating": rating,
        "would_repeat": would_repeat,
        "comments": comments,
    }
    db.surveys[s["id"]] = s
    # reputation recompute + auto suspend/reinstate cascade
    project = db.projects.get(reg["project_id"])
    if project is not None:
        partner = db.partners.get(project["nonprofit_id"])
        if partner is not None:
            refresh_partner_reputation(partner)
    return success_object(ser_survey(s), 201)


@bp.get("/feedback-surveys")
def list_surveys():
    authenticate(["Any"])
    items = list(db.surveys.values())
    val = request.args.get("registration_id")
    if val is not None:
        items = [s for s in items if s["registration_id"] == val]
    return success_list([ser_survey(s) for s in sort_entities(items)])


@bp.get("/feedback-surveys/<surveyId>")
def get_survey(surveyId):
    authenticate(["Any"])
    s = db.surveys.get(surveyId)
    if s is None:
        raise_err(ERR_SURVEY_NOT_FOUND, "feedback survey not found")
    return success_object(ser_survey(s))
