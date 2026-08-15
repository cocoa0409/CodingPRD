"""VarietyTrial endpoints (PRD 3.1): open, record-panel, decide."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_TRIAL_CRITERIA_NOT_MET,
    ERR_TRIAL_NOT_FOUND,
    ERR_VARIETY_NOT_FOUND,
)
from middleware import get_body, req_int, req_num, req_str, require_roles
from response import success, serialize
from services import new_resource, touch
from routes.listing import list_response

bp = Blueprint("trials", __name__)

RW = ("Grower", "OpsManager")


@bp.post("/variety-trials")
@require_roles("Grower")
def create_trial():
    body = get_body()
    variety_id = req_str(body, "variety_id")
    sow_date = req_str(body, "sow_date")
    chef_panel_size = req_int(body, "chef_panel_size")
    yield_score = req_num(body, "yield_score")
    variety = db.varieties.get(variety_id)
    if variety is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if chef_panel_size <= 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "chef_panel_size must be positive.")
    if yield_score < 0 or yield_score > 10:
        raise ApiError(400, ERR_INVALID_REQUEST, "yield_score must be in [0.0, 10.0].")
    rec = new_resource(
        {
            "variety_id": variety_id,
            "sow_date": sow_date,
            "chef_panel_size": chef_panel_size,
            "avg_flavor_score": None,
            "yield_score": float(yield_score),
            "decision": "PENDING",
        }
    )
    db.trials[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/variety-trials")
@require_roles(*RW)
def list_trials():
    variety_id = request.args.get("variety_id")
    records = list(db.trials.values())
    if variety_id is not None:
        records = [r for r in records if r["variety_id"] == variety_id]
    return list_response(records)


@bp.get("/variety-trials/<tid>")
@require_roles(*RW)
def get_trial(tid):
    rec = db.trials.get(tid)
    if rec is None:
        raise ApiError(404, ERR_TRIAL_NOT_FOUND, "variety trial id does not exist.")
    return success(serialize(rec), "object", 200)


@bp.post("/variety-trials/<tid>/record-panel")
@require_roles("Grower")
def record_panel(tid):
    trial = db.trials.get(tid)
    if trial is None:
        raise ApiError(404, ERR_TRIAL_NOT_FOUND, "variety trial id does not exist.")
    body = get_body()
    scores = body.get("scores")
    if not isinstance(scores, list) or not scores:
        raise ApiError(400, ERR_INVALID_REQUEST, "scores must be a non-empty list.")
    parsed = []
    for s in scores:
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            raise ApiError(400, ERR_INVALID_REQUEST, "scores must contain numbers.")
        parsed.append(Decimal(str(s)))
    if trial["decision"] != "PENDING":
        raise ApiError(409, ERR_INVALID_STATE, "Trial already decided.")
    variety = db.varieties.get(trial["variety_id"])
    if variety is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if variety["stage"] != "TRIAL":
        raise ApiError(409, ERR_INVALID_STATE, "Variety is not in TRIAL stage.")
    if len(parsed) != trial["chef_panel_size"]:
        raise ApiError(
            400,
            ERR_INVALID_REQUEST,
            "scores must contain exactly chef_panel_size entries.",
        )
    avg = (sum(parsed) / Decimal(len(parsed))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    trial["avg_flavor_score"] = float(avg)
    touch(trial)
    # Scores from the full panel are in: variety TRIAL -> EVALUATION; the trial
    # itself remains PENDING until an explicit decide.
    variety["stage"] = "EVALUATION"
    touch(variety)
    return success(serialize(trial), "object", 200)


@bp.post("/variety-trials/<tid>/decide")
@require_roles("Grower")
def decide_trial(tid):
    trial = db.trials.get(tid)
    if trial is None:
        raise ApiError(404, ERR_TRIAL_NOT_FOUND, "variety trial id does not exist.")
    body = get_body()
    outcome = req_str(body, "outcome")
    if outcome not in ("ADOPT", "RETRIAL"):
        raise ApiError(400, ERR_INVALID_REQUEST, "outcome must be ADOPT or RETRIAL.")
    if trial["decision"] != "PENDING":
        raise ApiError(409, ERR_INVALID_STATE, "Trial already decided.")
    variety = db.varieties.get(trial["variety_id"])
    if variety is None:
        raise ApiError(404, ERR_VARIETY_NOT_FOUND, "variety_id does not exist.")
    if variety["stage"] != "EVALUATION":
        raise ApiError(409, ERR_INVALID_STATE, "Variety is not in EVALUATION stage.")
    if outcome == "ADOPT":
        avg = trial["avg_flavor_score"]
        if (
            avg is None
            or Decimal(str(avg)) < Decimal("6.0")
            or Decimal(str(trial["yield_score"])) < Decimal("5.0")
        ):
            raise ApiError(
                409,
                ERR_TRIAL_CRITERIA_NOT_MET,
                "Adoption requires avg_flavor_score >= 6.0 and yield_score >= 5.0.",
            )
        trial["decision"] = "ADOPTED"
        variety["stage"] = "LISTED"
    else:  # RETRIAL — revision loop back to TRIAL
        trial["decision"] = "REJECTED"
        variety["stage"] = "TRIAL"
    touch(trial)
    touch(variety)
    return success(serialize(trial), "object", 200)
