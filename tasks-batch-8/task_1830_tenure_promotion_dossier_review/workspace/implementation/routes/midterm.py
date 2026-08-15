"""MidTenureReview endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CASE_NOT_FOUND,
    ERR_MIDTERM_REVIEW_NOT_FOUND,
    ERR_INVALID_MIDTERM_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch
from util import clock_stamp
from validate import get_body, req_enum, req_int, require_path, raw_str

bp = Blueprint("midterm_reviews", __name__)

OUTCOMES = {"SATISFACTORY", "CONCERNS", "UNSATISFACTORY"}


@bp.post("/midterm-reviews")
def create_midterm():
    authorized(["ProvostOfficer"])
    body = get_body()
    # Priority 4: case FK existence.
    case_id_raw = raw_str(body, "case_id")
    if case_id_raw is not None and db["cases"].get(case_id_raw) is None:
        raise_error(ERR_CASE_NOT_FOUND, "case_id does not resolve")
    # Priority 9: shape (review_year must be >= 1).
    from validate import req_str
    case_id = req_str(body, "case_id")
    review_year = req_int(body, "review_year", minimum=1)
    rec = new_record("midterm_reviews", {
        "case_id": case_id,
        "review_year": review_year,
        "outcome": None,
        "status": "IN_PROGRESS",
        "completed_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/midterm-reviews")
def list_midterms():
    return list_response("midterm_reviews", {
        "case_id": request.args.get("case_id"),
    })


@bp.get("/midterm-reviews/<rid>")
def get_midterm(rid):
    return get_one("midterm_reviews", rid, ERR_MIDTERM_REVIEW_NOT_FOUND)


@bp.post("/midterm-reviews/<rid>/complete")
def complete_midterm(rid):
    authorized(["ProvostOfficer"])
    rec = require_path("midterm_reviews", rid, ERR_MIDTERM_REVIEW_NOT_FOUND)
    if rec["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_MIDTERM_STATE, "mid-tenure review already COMPLETED")
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    rec["outcome"] = outcome
    rec["completed_at"] = clock_stamp()
    rec["status"] = "COMPLETED"
    touch(rec)
    return success_object(public(rec))
