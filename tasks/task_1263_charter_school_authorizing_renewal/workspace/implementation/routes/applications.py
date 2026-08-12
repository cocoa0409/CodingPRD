"""Applications + capacity interviews (PRD §3.1)."""
from flask import Blueprint

import db
import errors
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    require_field,
    require_int,
    require_non_empty_string,
    require_number,
    require_roles,
)
from response import success_object
from routes.common import filter_eq, get_or_404, paginate
from services import calc, cascade

bp = Blueprint("applications", __name__)


def application_view(a: dict) -> dict:
    return a


@bp.post("/authorizer/applications")
def create_application():
    user_id, _role = require_roles(["Applicant"])
    data = body()
    school_name = require_non_empty_string(data, "school_name")
    founding_group = require_non_empty_string(data, "founding_group")
    cycle_year = require_int(data, "cycle_year")
    proposed_grades = require_non_empty_string(data, "proposed_grades")
    record = db.stamp_new({
        "school_name": school_name,
        "founding_group": founding_group,
        "cycle_year": cycle_year,
        "proposed_grades": proposed_grades,
        "review_scores": [],
        "rubric_complete": False,
        "rubric_score": None,
        "interview_score": None,
        "composite_score": None,
        "composite_variant": None,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "denial_reason": None,
    })
    db.insert("applications", record)
    return success_object(record, 201)


@bp.get("/authorizer/applications")
def list_applications():
    require_roles(ALL_ROLES)
    records = db.all_records("applications")
    records = filter_eq(records, "status", _arg("status"))
    records = filter_eq(records, "cycle_year", _arg("cycle_year"))
    return paginate(records)


def _arg(name):
    from flask import request
    return request.args.get(name)


@bp.get("/authorizer/applications/<id>")
def get_application(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("applications", id))


@bp.post("/authorizer/applications/<id>/accept-intake")
def accept_intake(id):
    require_roles(["AuthorizerStaff"])
    app_rec = get_or_404("applications", id)
    if app_rec["status"] != "SUBMITTED":
        raise_error(errors.ERR_APPLICATION_INVALID_STATE, "Application is not SUBMITTED")
    app_rec["status"] = "UNDER_REVIEW"
    db.touch(app_rec)
    return success_object(app_rec)


@bp.post("/authorizer/applications/<id>/scores")
def post_score(id):
    user_id, _role = require_roles(["ApplicationReviewer"])
    app_rec = get_or_404("applications", id)
    # State precondition (layer 4) before constraint (layer 7).
    if app_rec["status"] != "UNDER_REVIEW":
        raise_error(errors.ERR_APPLICATION_INVALID_STATE, "Scores accepted only while UNDER_REVIEW")
    data = body()
    criterion = require_non_empty_string(data, "criterion")
    if criterion not in calc.CRITERIA:
        raise_error(errors.ERR_INVALID_REQUEST, f"Unknown criterion: {criterion}")
    score = require_number(data, "score")
    for entry in app_rec["review_scores"]:
        if entry["reviewer_user_id"] == user_id and entry["criterion"] == criterion:
            raise_error(errors.ERR_DUPLICATE_RECORD, "Reviewer already scored this criterion")
    app_rec["review_scores"].append({
        "reviewer_user_id": user_id,
        "criterion": criterion,
        "score": score,
    })
    cascade.recompute_application_scores(app_rec)
    db.touch(app_rec)
    return success_object(app_rec, 201)


@bp.post("/authorizer/applications/<id>/interviews")
def schedule_interview(id):
    require_roles(["AuthorizerStaff"])
    app_rec = get_or_404("applications", id)
    if app_rec["status"] != "UNDER_REVIEW":
        raise_error(errors.ERR_APPLICATION_INVALID_STATE, "Interview scheduling requires UNDER_REVIEW")
    data = body()
    start_raw = require_non_empty_string(data, "scheduled_start")
    end_raw = require_non_empty_string(data, "scheduled_end")
    panelists = require_field(data, "panelist_user_ids")
    if not isinstance(panelists, list) or not panelists or not all(isinstance(p, str) and p for p in panelists):
        raise_error(errors.ERR_INVALID_REQUEST, "panelist_user_ids must be a non-empty array of strings")
    from clock import parse as parse_iso
    try:
        start = parse_iso(start_raw)
        end = parse_iso(end_raw)
    except ValueError:
        raise_error(errors.ERR_INVALID_REQUEST, "Invalid scheduled_start/scheduled_end")
    if start >= end:
        raise_error(errors.ERR_INVALID_REQUEST, "scheduled_start must be earlier than scheduled_end")
    # One non-CANCELLED interview per application (layer 7 aggregate guard).
    for iv in db.all_records("interviews"):
        if iv["application_id"] == id and iv["status"] != "CANCELLED":
            raise_error(errors.ERR_INTERVIEW_ALREADY_ACTIVE, "Application already has a non-CANCELLED interview")
    # SOD: no panelist may appear among the rubric scorers (layer 5).
    scorer_ids = {e["reviewer_user_id"] for e in app_rec["review_scores"]}
    if any(p in scorer_ids for p in panelists):
        raise_error(
            errors.ERR_SOD_REVIEWER_PANEL_CONFLICT,
            "A panelist appears in the application's review_scores",
        )
    # Panel overlap: half-open intervals; adjacency allowed (layer 6).
    for iv in db.all_records("interviews"):
        if iv["status"] != "SCHEDULED":
            continue
        if not any(p in iv["panelist_user_ids"] for p in panelists):
            continue
        iv_start = parse_iso(iv["scheduled_start"])
        iv_end = parse_iso(iv["scheduled_end"])
        # Half-open overlap: [start,end) intersects [iv_start,iv_end)
        if start < iv_end and iv_start < end:
            raise_error(errors.ERR_PANEL_TIME_OVERLAP, "A panelist already holds an overlapping SCHEDULED interview")
    record = db.stamp_new({
        "application_id": id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "panelist_user_ids": list(panelists),
        "panel_score": None,
        "status": "SCHEDULED",
    })
    db.insert("interviews", record)
    return success_object(record, 201)


@bp.get("/authorizer/applications/<id>/interviews")
def list_application_interviews(id):
    require_roles(ALL_ROLES)
    get_or_404("applications", id)
    records = [iv for iv in db.all_records("interviews") if iv["application_id"] == id]
    return paginate(records)


@bp.get("/authorizer/applications/<id>/schools")
def list_application_schools(id):
    require_roles(ALL_ROLES)
    get_or_404("applications", id)
    records = [s for s in db.all_records("schools") if s["application_id"] == id]
    return paginate(records)


@bp.post("/authorizer/applications/<id>/advance-to-board")
def advance_to_board(id):
    require_roles(["AuthorizerStaff"])
    app_rec = get_or_404("applications", id)
    if app_rec["status"] != "UNDER_REVIEW":
        raise_error(errors.ERR_APPLICATION_INVALID_STATE, "Application is not UNDER_REVIEW")
    if not app_rec["rubric_complete"] or cascade.scored_interview_for(id) is None:
        raise_error(errors.ERR_BOARD_REVIEW_BLOCKED, "Rubric incomplete or interview not SCORED")
    # Composite frozen as FINAL variant at this transition (already FINAL after scoring).
    app_rec["status"] = "BOARD_REVIEW"
    db.touch(app_rec)
    return success_object(app_rec)


@bp.post("/authorizer/applications/<id>/decide")
def decide_application(id):
    user_id, _role = require_roles(["BoardMember"])
    app_rec = get_or_404("applications", id)
    if app_rec["status"] != "BOARD_REVIEW":
        raise_error(errors.ERR_APPLICATION_INVALID_STATE, "Application is not BOARD_REVIEW")
    data = body()
    outcome = require_non_empty_string(data, "outcome")
    if outcome not in ("APPROVED", "DENIED"):
        raise_error(errors.ERR_INVALID_REQUEST, "outcome must be APPROVED or DENIED")
    if outcome == "APPROVED":
        composite = app_rec.get("composite_score")
        if composite is None or composite < calc.APPROVAL_THRESHOLD:
            raise_error(errors.ERR_COMPOSITE_BELOW_THRESHOLD, "composite_score below 75.0")
        app_rec["status"] = "APPROVED"
        app_rec["decided_by_user_id"] = user_id
        app_rec["denial_reason"] = None
        db.touch(app_rec)
        # Approval cascade: create School PRE_OPENING with all standings GOOD.
        school = db.stamp_new({
            "application_id": app_rec["id"],
            "school_name": app_rec["school_name"],
            "status": "PRE_OPENING",
            "academic_standing": "GOOD",
            "financial_standing": "GOOD",
            "operational_standing": "GOOD",
            "current_contract_id": None,
        })
        db.insert("schools", school)
    else:
        reason = data.get("denial_reason")
        if not isinstance(reason, str) or reason == "":
            raise_error(errors.ERR_INVALID_REQUEST, "denial_reason must be supplied and non-empty")
        app_rec["status"] = "DENIED"
        app_rec["decided_by_user_id"] = user_id
        app_rec["denial_reason"] = reason
        db.touch(app_rec)
        cascade.cancel_scheduled_interviews(app_rec["id"])
    return success_object(app_rec)


# ---------------------------------------------------------------------------
# Capacity interview scoring
# ---------------------------------------------------------------------------

bp_interviews = Blueprint("interviews", __name__)


@bp_interviews.post("/authorizer/interviews/<id>/score")
def score_interview(id):
    user_id, _role = require_roles(["ApplicationReviewer"])
    interview = get_or_404("interviews", id)
    if interview["status"] != "SCHEDULED":
        raise_error(errors.ERR_INTERVIEW_INVALID_STATE, "Interview is not SCHEDULED")
    if user_id not in interview["panelist_user_ids"]:
        raise_error(errors.ERR_NOT_PANELIST, "Caller is not a listed panelist")
    data = body()
    panel_score = require_number(data, "panel_score")
    if panel_score < 0 or panel_score > 100:
        raise_error(errors.ERR_INVALID_REQUEST, "panel_score must be within 0..100")
    interview["panel_score"] = panel_score
    interview["status"] = "SCORED"
    db.touch(interview)
    app_rec = db.get("applications", interview["application_id"])
    if app_rec is not None:
        app_rec["interview_score"] = panel_score
        cascade.recompute_application_scores(app_rec)
        db.touch(app_rec)
    return success_object(interview)
