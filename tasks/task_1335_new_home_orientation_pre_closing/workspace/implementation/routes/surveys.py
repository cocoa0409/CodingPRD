"""Feedback surveys: read/list, submit within window, expire-due sweep
(PRD §3.8)."""
from flask import Blueprint, request

import db
from db import homes, surveys
from errors import err_invalid_state, err_not_found, err_survey_expired
from logic import survey_composite
from middleware import (
    ROLE_BUYER, ROLE_MANAGER, ROLE_REP, check_buyer_ownership, require_roles,
)
from response import paginate, success_list, success_object
from validation import json_body, opt_str, req_bool, req_int

bp = Blueprint("surveys", __name__)

READ_ROLES = (ROLE_MANAGER, ROLE_REP, ROLE_BUYER)


def _get_survey_or_404(survey_id):
    survey = surveys.get(survey_id)
    if survey is None:
        raise err_not_found("Feedback survey %s not found." % survey_id)
    return survey


def _req_rating(body, field):
    v = req_int(body, field)
    if v < 1 or v > 5:
        from errors import err_validation
        raise err_validation("Field '%s' must be within 1..5." % field)
    return v


@bp.get("/api/feedback-surveys/<survey_id>")
def get_survey(survey_id):
    require_roles(*READ_ROLES)
    return success_object(db.public(_get_survey_or_404(survey_id)))


@bp.get("/api/feedback-surveys")
def list_surveys():
    require_roles(*READ_ROLES)
    items = list(surveys.values())
    for f in ("home_id", "appointment_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if s.get(f) == v]
    items.sort(key=db.sort_key)
    page, pagination = paginate(items, request.args)
    return success_list([db.public(s) for s in page], pagination)


@bp.post("/api/feedback-surveys/expire-due")
def expire_due_surveys():
    require_roles(ROLE_MANAGER)
    now = db.now()
    expired_ids = []
    for s in sorted(surveys.values(), key=db.sort_key):
        if s["status"] == "ISSUED" and now > db.parse_dt(s["window_closes_at"]):
            s["status"] = "EXPIRED"
            db.touch(s)
            expired_ids.append(s["id"])
    return success_object({
        "expired_count": len(expired_ids),
        "expired_survey_ids": expired_ids,
    })


@bp.post("/api/feedback-surveys/<survey_id>/submit")
def submit_survey(survey_id):
    actor = require_roles(ROLE_BUYER)
    # Priority 3 ownership before schema when the record resolves.
    survey = surveys.get(survey_id)
    if survey is not None:
        check_buyer_ownership(actor, homes[survey["home_id"]])
    body = json_body()
    overall = _req_rating(body, "overall_rating")
    systems = _req_rating(body, "systems_demo_rating")
    timeliness = _req_rating(body, "timeliness_rating")
    recommend = req_bool(body, "would_recommend")
    comments = opt_str(body, "comments")
    if survey is None:
        raise err_not_found("Feedback survey %s not found." % survey_id)

    if survey["status"] != "ISSUED":
        raise err_invalid_state("Only an ISSUED survey can be submitted.")
    if db.now() > db.parse_dt(survey["window_closes_at"]):
        raise err_survey_expired()

    survey["overall_rating"] = overall
    survey["systems_demo_rating"] = systems
    survey["timeliness_rating"] = timeliness
    survey["would_recommend"] = recommend
    survey["comments"] = comments
    survey["composite_score"] = survey_composite(overall, systems, timeliness, recommend)
    survey["submitted_at"] = db.fmt_dt(db.now())
    survey["status"] = "SUBMITTED"
    db.touch(survey)
    return success_object(db.public(survey))
