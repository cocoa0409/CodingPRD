"""NEPA / Section 106 review as a fork-join over two branches."""

from flask import Blueprint

import calc
import services
from db import add_days, db, fmt_dt, get_dt, new_record, now, serialize, set_dt
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, BOOLEAN, ROLE_ENVIRONMENTAL, STRING,
                        authenticate, f, validate_body)

bp = Blueprint("environmental", __name__)

NEPA_CATEGORIES = ["CATEGORICAL_EXCLUSION", "ENVIRONMENTAL_ASSESSMENT"]
BRANCHES = ["PUBLIC_NOTICE", "TRIBAL"]
FINDINGS = ["NO_ADVERSE_EFFECT", "ADVERSE_EFFECT"]

BRANCH_FIELD = {"PUBLIC_NOTICE": "public_notice_branch_status",
                "TRIBAL": "tribal_branch_status"}


@bp.post("/environmental-reviews")
def create_review():
    authenticate([ROLE_ENVIRONMENTAL])
    body = validate_body([
        f("candidate_id", STRING),
        f("nepa_category", STRING, enum=NEPA_CATEGORIES),
        f("section106_required", BOOLEAN),
    ])
    candidate = db.candidates.get(body["candidate_id"])
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404)

    for existing in services.reviews_of_candidate(candidate["id"]):
        if existing["status"] != "ADVERSE_EFFECT":
            raise ApiError("ERR_DUPLICATE_ENVIRONMENTAL_REVIEW", 409)

    jurisdiction = db.jurisdictions.get(candidate["jurisdiction_id"])
    landlord = db.landlords.get(candidate["landlord_id"])
    tribal = bool(jurisdiction is not None and jurisdiction["tribal_consultation_required"])
    if landlord is not None and landlord["entity_type"] == "TRIBAL_AUTHORITY":
        tribal = True

    review = new_record({
        "candidate_id": candidate["id"],
        "nepa_category": body["nepa_category"],
        "section106_required": body["section106_required"],
        "tribal_consultation_required": tribal,
        "tcns_notice_date": None,
        "tribal_response_deadline_date": None,
        "public_notice_branch_status": "NOT_STARTED",
        "tribal_branch_status": "NOT_STARTED",
        "status": "NOT_STARTED",
    })
    set_dt(review, "tcns_notice_date", None)
    set_dt(review, "tribal_response_deadline_date", None)
    db.environmental_reviews[review["id"]] = review
    return created(serialize(review))


@bp.get("/environmental-reviews")
def list_reviews():
    authenticate(ALL_ROLES)
    return listing("environmental_reviews", ["candidate_id", "status"])


@bp.get("/environmental-reviews/<review_id>")
def read_review(review_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("environmental_reviews", review_id)))


@bp.post("/environmental-reviews/<review_id>/screen")
def screen(review_id):
    authenticate([ROLE_ENVIRONMENTAL])
    validate_body([])
    review = fetch("environmental_reviews", review_id)
    if review["status"] != "NOT_STARTED":
        raise ApiError("ERR_INVALID_REVIEW_STATE", 409)

    updates = {"public_notice_branch_status": "PENDING", "status": "SCREENING"}
    if review["tribal_consultation_required"]:
        notice = now()
        deadline = add_days(notice, calc.TRIBAL_RESPONSE_DAYS)
        set_dt(review, "tcns_notice_date", notice)
        set_dt(review, "tribal_response_deadline_date", deadline)
        updates["tribal_branch_status"] = "PENDING"
        updates["tcns_notice_date"] = fmt_dt(notice)
        updates["tribal_response_deadline_date"] = fmt_dt(deadline)
    else:
        updates["tribal_branch_status"] = "NOT_APPLICABLE"
    services.apply(review, updates)
    return ok(serialize(review))


@bp.post("/environmental-reviews/<review_id>/branch-complete")
def branch_complete(review_id):
    authenticate([ROLE_ENVIRONMENTAL])
    body = validate_body([
        f("branch", STRING, enum=BRANCHES),
        f("finding", STRING, enum=FINDINGS),
    ])
    review = fetch("environmental_reviews", review_id)
    branch = body["branch"]
    field = BRANCH_FIELD[branch]

    if review["status"] not in ("SCREENING", "IN_CONSULTATION"):
        raise ApiError("ERR_INVALID_REVIEW_STATE", 409)
    if review[field] != "PENDING":
        raise ApiError("ERR_INVALID_REVIEW_STATE", 409)

    if branch == "TRIBAL":
        deadline = get_dt(review, "tribal_response_deadline_date")
        if deadline is not None and now() < deadline:
            raise ApiError("ERR_TRIBAL_RESPONSE_WINDOW_OPEN", 409)

    updates = {field: "COMPLETE"}
    public_status = review["public_notice_branch_status"]
    tribal_status = review["tribal_branch_status"]
    if branch == "PUBLIC_NOTICE":
        public_status = "COMPLETE"
    else:
        tribal_status = "COMPLETE"

    candidate = db.candidates.get(review["candidate_id"])
    if body["finding"] == "ADVERSE_EFFECT":
        updates["status"] = "ADVERSE_EFFECT"
        cleared = False
    elif public_status == "COMPLETE" and tribal_status in ("COMPLETE", "NOT_APPLICABLE"):
        updates["status"] = "CLEARED"
        cleared = True
    else:
        updates["status"] = "IN_CONSULTATION"
        cleared = None

    services.apply(review, updates)
    if cleared is not None and candidate is not None:
        services.apply(candidate, {"environmental_cleared": cleared})
    return ok(serialize(review))
