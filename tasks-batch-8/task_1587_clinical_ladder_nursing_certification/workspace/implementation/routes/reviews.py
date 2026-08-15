"""AnniversaryReview endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db
from errors import (err_cannot_demote_floor, err_invalid_request, err_invalid_state,
                    err_maintenance_score_insufficient, err_not_found)
from middleware import require_roles
from response import success_object
from serializers import review_view
from services.budget import recompute_budgets_for_unit
from services.calculations import (MAINTENANCE_THRESHOLD, add_years, calc_maintenance_score,
                                   record_risk_event, recompute_risk)
from util import require_fields, require_int, require_enum

bp = Blueprint("reviews", __name__)

DEMOTE_NEXT = {"CN_IV": "CN_III", "CN_III": "CN_II", "CN_II": "CN_I"}


def _get_nurse_or_404(nid):
    nurse = db.nurses.get(nid)
    if nurse is None:
        raise err_not_found("Nurse not found")
    return nurse


@bp.route("/clinical-ladder/anniversary-reviews", methods=["POST"])
def create_review():
    require_roles("ProgramAdmin")
    payload = request.get_json(silent=True)
    require_fields(payload, ["nurse_id", "review_year"])
    nurse_id = payload.get("nurse_id")
    if not isinstance(nurse_id, str):
        raise err_invalid_request("nurse_id must be a string")
    review_year = require_int(payload, "review_year")
    nurse = _get_nurse_or_404(nurse_id)

    now = clock.now()
    review = {
        "id": db.new_id(),
        "nurse_id": nurse["id"],
        "review_year": review_year,
        "maintenance_score": None,
        "outcome": "OPEN",
        "resolution_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.anniversary_reviews[review["id"]] = review
    return success_object(review_view(review), status=201)


@bp.route("/clinical-ladder/anniversary-reviews/<rid>/close", methods=["POST"])
def close_review(rid):
    require_roles("ProgramAdmin")
    review = db.anniversary_reviews.get(rid)
    if review is None:
        raise err_not_found("AnniversaryReview not found")
    payload = request.get_json(silent=True)
    require_fields(payload, ["outcome"])
    outcome = require_enum(payload, "outcome", {"SUSTAIN", "DEMOTE"})
    resolution_reason = payload.get("resolution_reason")
    if resolution_reason is not None and not isinstance(resolution_reason, str):
        raise err_invalid_request("resolution_reason must be a string")

    if review["outcome"] != "OPEN":
        raise err_invalid_state("Review is not OPEN")

    nurse = _get_nurse_or_404(review["nurse_id"])
    score = calc_maintenance_score(nurse)
    now = clock.now()

    # Floor rule evaluated before the threshold rule (PRD 2.8 / 3.5)
    if outcome == "DEMOTE":
        if not resolution_reason:
            raise err_invalid_request("resolution_reason is required on DEMOTE")
        if nurse["current_level"] == "CN_I":
            raise err_cannot_demote_floor()
    else:  # SUSTAIN
        if score < MAINTENANCE_THRESHOLD:
            raise err_maintenance_score_insufficient()

    review["maintenance_score"] = score
    review["outcome"] = outcome
    review["resolution_reason"] = resolution_reason
    review["updated_at"] = now
    review["version"] += 1

    if outcome == "SUSTAIN":
        # Anniversary rolls forward one year, extending pay for another cycle
        if nurse["differential_activated_at"] is not None:
            nurse["differential_activated_at"] = add_years(nurse["differential_activated_at"], 1)
            nurse["updated_at"] = now
            nurse["version"] += 1
    else:  # DEMOTE
        nurse["current_level"] = DEMOTE_NEXT[nurse["current_level"]]
        nurse["differential_status"] = "SUSPENDED"
        nurse["updated_at"] = now
        nurse["version"] += 1
        record_risk_event(nurse["id"], "demotion")
        recompute_risk(nurse["id"])
        recompute_budgets_for_unit(nurse["home_unit"])

    return success_object(review_view(review))
