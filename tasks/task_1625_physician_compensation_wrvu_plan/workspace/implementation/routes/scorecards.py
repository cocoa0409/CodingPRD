"""QualityScorecard endpoints (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_RESOURCE, ERR_NOT_OWN_RESOURCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from services.ledger import compute_quality_bonus
from validate import get_body, req_period, req_score, require_path_resource

bp = Blueprint("scorecards", __name__)

SCORECARD_READ_ROLES = ["CompAnalyst", "CompCommittee", "Physician"]


def _check_agreement_ownership(caller, agreement):
    if caller.role == "Physician" and agreement["physician_id"] != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own resources")


@bp.post("/physician-agreements/<rid>/quality-scorecards")
def create_scorecard(rid):
    authorized(["CompAnalyst"])
    agr = require_path_resource("physician_agreements", rid)
    body = get_body()
    # Priority 14: payload shape
    period = req_period(body, "period")
    measures = body.get("measures")
    if not isinstance(measures, list) or len(measures) < 1:
        raise_error(ERR_VALIDATION, "measures must be a non-empty array")
    seen_codes = set()
    for m in measures:
        if not isinstance(m, dict):
            raise_error(ERR_VALIDATION, "each measure must be an object")
        code = m.get("measure_code")
        if not isinstance(code, str) or not code:
            raise_error(ERR_VALIDATION, "measure.measure_code must be a non-empty string")
        if code in seen_codes:
            raise_error(ERR_VALIDATION, "measure_code must be unique within the scorecard")
        seen_codes.add(code)
        weight = m.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            raise_error(ERR_VALIDATION, "measure.weight must be an integer > 0")
        req_score(m.get("threshold_score"), "measure.threshold_score")
        req_score(m.get("score"), "measure.score")
    # Priority 21: one scorecard per (agreement, period)
    for sc in db["quality_scorecards"].values():
        if sc["agreement_id"] == agr["id"] and sc["period"] == period:
            raise_error(ERR_DUPLICATE_RESOURCE,
                        "a scorecard already exists for this agreement and period")
    rec = new_record("quality_scorecards", {
        "agreement_id": agr["id"],
        "period": period,
        "measures": measures,
        "quality_bonus_cents": None,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/physician-agreements/<rid>/quality-scorecards")
def list_scorecards(rid):
    caller = authorized(SCORECARD_READ_ROLES)
    agr = db["physician_agreements"].get(rid)
    if agr is not None:
        _check_agreement_ownership(caller, agr)
    if agr is None:
        raise_error(ERR_NOT_FOUND, f"agreement not found: {rid}")
    return list_response("quality_scorecards", {"agreement_id": rid})


@bp.post("/quality-scorecards/<rid>/finalize")
def finalize_scorecard(rid):
    authorized(["CompAnalyst"])
    sc = require_path_resource("quality_scorecards", rid)
    if sc["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT scorecard can be finalized")
    agr = db["physician_agreements"][sc["agreement_id"]]
    plan = db["comp_plans"][agr["plan_id"]]
    sc["quality_bonus_cents"] = compute_quality_bonus(plan, sc["measures"])
    sc["status"] = "FINALIZED"
    touch("quality_scorecards", sc)
    return success_object(public(sc))
