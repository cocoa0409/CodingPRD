"""RiskScore endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE_RISK_SCORE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_RISK_MODEL_MISMATCH,
    ERR_YEAR_LOCKED,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("risk_scores", __name__)

RISK_MODELS = {"PROSPECTIVE", "CONCURRENT"}


def _get_score_or_404(score_id: str) -> dict:
    score = db.risk_scores.get(score_id)
    if score is None:
        raise_err(ERR_NOT_FOUND, "RiskScore id does not exist")
    return score


@bp.route("/vbc/risk-scores", methods=["POST"])
@require_roles("ActuaryAnalyst")
def create_risk_score(_user_id: str, _role: str):
    body = get_json_body()
    # Priority 3: body FK existence.
    raw_member = body.get("member_id")
    if isinstance(raw_member, str) and raw_member != "" and raw_member not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")
    raw_year = body.get("performance_year_id")
    if isinstance(raw_year, str) and raw_year != "" and raw_year not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")
    # Priority 5: shape (score_milli scalar range 1..10000).
    reject_unknown_fields(body, {"member_id", "performance_year_id", "model_used", "score_milli"})
    member_id = require_string(body, "member_id")
    performance_year_id = require_string(body, "performance_year_id")
    model_used = require_enum(body, "model_used", RISK_MODELS)
    score_milli = require_int(body, "score_milli", minimum=1, maximum=10000)
    if member_id not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")
    if performance_year_id not in db.performance_years:
        raise_err(ERR_NOT_FOUND, "performance_year_id does not exist")

    year = db.performance_years[performance_year_id]
    contract = engine.contract_of_year(year)
    # Priority 7 (pinning): model_used must equal the contract's pinned risk_model.
    if model_used != contract["risk_model"]:
        raise_err(ERR_RISK_MODEL_MISMATCH, "model_used differs from the contract's pinned risk_model")
    # Priority 11: one non-SUPERSEDED score per (member, year, model_used).
    for score in db.risk_scores.values():
        if (
            score["member_id"] == member_id
            and score["performance_year_id"] == performance_year_id
            and score["model_used"] == model_used
            and score["score_status"] != "SUPERSEDED"
        ):
            raise_err(ERR_DUPLICATE_RISK_SCORE, "A non-SUPERSEDED score already exists for (member, year, model_used)")

    score = {
        "member_id": member_id,
        "performance_year_id": performance_year_id,
        "model_used": model_used,
        "score_milli": score_milli,
        "score_status": "PRELIMINARY",
    }
    db.stamp_new(score)
    db.risk_scores[score["id"]] = score
    return success_object(score, 201)


@bp.route("/vbc/risk-scores", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_risk_scores(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.risk_scores.values()))
    items = apply_filters(items, ["member_id", "performance_year_id", "model_used", "score_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/risk-scores/<score_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_risk_score(score_id: str, _user_id: str, _role: str):
    return success_object(_get_score_or_404(score_id))


@bp.route("/vbc/risk-scores/<score_id>/finalize", methods=["POST"])
@require_roles("ActuaryAnalyst")
def finalize_risk_score(score_id: str, _user_id: str, _role: str):
    score = _get_score_or_404(score_id)
    if score["score_status"] != "PRELIMINARY":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PRELIMINARY score can be finalized")
    score["score_status"] = "FINAL"
    db.touch(score)
    # Side effect: when the year's rollups are already computed
    # (ATTRIBUTION_LOCKED or later), recompute them; flag the settlement.
    year = db.performance_years.get(score["performance_year_id"])
    if year is not None:
        engine.after_population_mutation(year)
    return success_object(score)


@bp.route("/vbc/risk-scores/<score_id>/supersede", methods=["POST"])
@require_roles("ActuaryAnalyst")
def supersede_risk_score(score_id: str, _user_id: str, _role: str):
    score = _get_score_or_404(score_id)
    if score["score_status"] not in ("PRELIMINARY", "FINAL"):
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a PRELIMINARY or FINAL score can be superseded")
    was_final = score["score_status"] == "FINAL"
    year = db.performance_years.get(score["performance_year_id"])
    if was_final:
        # FINAL -> SUPERSEDED requires the year not be SETTLED/CLOSED.
        if year is not None and year["year_status"] in ("SETTLED", "CLOSED"):
            raise_err(ERR_YEAR_LOCKED, "Year is locked for data mutations")
    score["score_status"] = "SUPERSEDED"
    db.touch(score)
    if was_final and year is not None:
        # Rollups recomputed without this score (missing FINAL falls back to
        # DEFAULT_SCORE_MILLI); settlement flagged when PROVISIONAL/FINALIZED.
        engine.after_population_mutation(year)
    return success_object(score)
