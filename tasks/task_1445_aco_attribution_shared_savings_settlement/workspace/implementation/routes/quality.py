"""Quality scores: report, review (segregation of duties), resubmit."""
from flask import Blueprint, request

import db
from errors import (ApiError, bad_request, not_found, ERR_PERIOD_NOT_OPEN,
                    ERR_DUPLICATE_MEASURE_SCORE, ERR_SCORE_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import (require_roles, ROLE_REPORTER, ROLE_AUDITOR,
                        ALL_DOMAIN_ROLES)
from response import success, list_success
from serializers import quality_score_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("quality", __name__)

SCORE_SPEC = {
    "agreement_period_id": {"type": "string", "required": True},
    "measure_code": {"type": "string", "required": True},
    "numerator": {"type": "int", "required": True, "min": 0},
    "denominator": {"type": "int", "required": True, "min": 1},
    "max_points": {"type": "int", "required": True, "min": 1},
}

REVIEW_SPEC = {
    "outcome": {"type": "enum", "enum": ["VALIDATED", "REJECTED"],
                "required": True},
    "reviewer_note": {"type": "string", "required": False},
}

RESUBMIT_SPEC = {
    "numerator": {"type": "int", "required": True, "min": 0},
    "denominator": {"type": "int", "required": True, "min": 1},
}


@bp.post("/aco/quality-scores")
def create_score():
    uid, _ = require_roles([ROLE_REPORTER])
    body = validate_body(get_json_body(), SCORE_SPEC)
    if body["numerator"] > body["denominator"]:
        raise bad_request("numerator must not exceed denominator")
    period = db.periods.get(body["agreement_period_id"])
    if period is None:
        raise not_found("Agreement period not found")
    # Quality reporting is allowed while the period is OPEN or
    # ASSIGNMENT_LOCKED; any other posture draws ERR_PERIOD_NOT_OPEN.
    if period["status"] not in ("OPEN", "ASSIGNMENT_LOCKED"):
        raise ApiError(ERR_PERIOD_NOT_OPEN, 409,
                       "Quality reporting requires an OPEN or "
                       "ASSIGNMENT_LOCKED period")
    # One score per (period, measure_code) across ALL scores; resubmit edits
    # in place so corrections never trip this rule.
    for existing in db.quality_scores.values():
        if (existing["agreement_period_id"] == period["id"]
                and existing["measure_code"] == body["measure_code"]):
            raise ApiError(ERR_DUPLICATE_MEASURE_SCORE, 409,
                           "A score for this measure already exists in this period")
    rate, points = calc.score_rate_and_points(
        body["numerator"], body["denominator"], body["max_points"])
    score = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "measure_code": body["measure_code"],
        "numerator": body["numerator"],
        "denominator": body["denominator"],
        "max_points": body["max_points"],
        "performance_rate": rate,
        "earned_points": points,
        "reported_by_user_id": uid,
        "status": "REPORTED",
    })
    db.quality_scores[score["id"]] = score
    return success(quality_score_out(score), 201)


@bp.get("/aco/quality-scores/<score_id>")
def get_score(score_id):
    require_roles(ALL_DOMAIN_ROLES)
    score = db.quality_scores.get(score_id)
    if score is None:
        raise not_found("Quality score not found")
    return success(quality_score_out(score))


@bp.get("/aco/quality-scores")
def list_scores():
    require_roles(ALL_DOMAIN_ROLES)
    items = list(db.quality_scores.values())
    for param in ("agreement_period_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    items.sort(key=lambda s: s["created_at"])
    return list_success([quality_score_out(s) for s in items])


@bp.post("/aco/quality-scores/<score_id>/review")
def review_score(score_id):
    uid, _ = require_roles([ROLE_AUDITOR])
    body = validate_body(get_json_body(), REVIEW_SPEC)
    score = db.quality_scores.get(score_id)
    if score is None:
        raise not_found("Quality score not found")
    # Entity transition precondition (priority 7) precedes segregation of
    # duties (priority 8).
    if score["status"] != "REPORTED":
        raise ApiError(ERR_SCORE_INVALID_STATE, 409,
                       "Review requires the score to be REPORTED")
    if uid == score["reported_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Reviewer must differ from the reporting user")
    score["status"] = body["outcome"]
    db.bump(score)
    return success(quality_score_out(score))


@bp.post("/aco/quality-scores/<score_id>/resubmit")
def resubmit_score(score_id):
    uid, _ = require_roles([ROLE_REPORTER])
    body = validate_body(get_json_body(), RESUBMIT_SPEC)
    if body["numerator"] > body["denominator"]:
        raise bad_request("numerator must not exceed denominator")
    score = db.quality_scores.get(score_id)
    if score is None:
        raise not_found("Quality score not found")
    if score["status"] != "REJECTED":
        raise ApiError(ERR_SCORE_INVALID_STATE, 409,
                       "Resubmit requires the score to be REJECTED")
    rate, points = calc.score_rate_and_points(
        body["numerator"], body["denominator"], score["max_points"])
    score["numerator"] = body["numerator"]
    score["denominator"] = body["denominator"]
    score["performance_rate"] = rate
    score["earned_points"] = points
    score["reported_by_user_id"] = uid
    score["status"] = "REPORTED"
    db.bump(score)
    return success(quality_score_out(score))
