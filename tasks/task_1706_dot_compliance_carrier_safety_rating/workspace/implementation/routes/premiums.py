"""InsurancePremiumModel endpoints (PRD 3.9): model, quote, recompute, bind."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE,
    ERR_POLICY_PERIOD_OVERLAP, ERR_PREMIUM_MODEL_NOT_DRAFT,
    ERR_PREMIUM_MODEL_NOT_QUOTED, ERR_PREMIUM_MODEL_NOT_STALE,
    ERR_PREMIUM_INPUT_STALE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import stamp_new, touch
from validate import (
    get_body, req_str, req_int, req_enum, opt_enum, opt_int, opt_str_list,
    req_datetime, require_path_resource, require_ref,
)
from util import new_id, parse_datetime

bp = Blueprint("premiums", __name__)

ROLE = ["InsuranceAnalyst"]
SCENARIOS = ["BASELINE", "PROJECTED"]
ASSUME_RATINGS = ["NONE", "SATISFACTORY", "CONDITIONAL"]
OVERLAP_STATUSES = ("DRAFT", "QUOTED", "BOUND")  # STALE no longer participates


def _check_period_overlap(carrier_id, start, end, exclude_id=None):
    """Closed-interval overlap: touching endpoints already count as overlap."""
    for m in db["insurance_premium_models"].values():
        if m["carrier_id"] != carrier_id or m["status"] not in OVERLAP_STATUSES:
            continue
        if exclude_id is not None and m["id"] == exclude_id:
            continue
        m_start = parse_datetime(m["policy_period_start"])
        m_end = parse_datetime(m["policy_period_end"])
        if start <= m_end and m_start <= end:
            raise_error(ERR_POLICY_PERIOD_OVERLAP,
                        "policy period overlaps an existing model's period")


@bp.post("/safety/insurance-premium-models")
def create_model():
    authorized(ROLE)
    body = get_body()
    # Stage 3: shape
    carrier_id = req_str(body, "carrier_id")
    period_start = req_datetime(body, "policy_period_start")
    period_end = req_datetime(body, "policy_period_end")
    base_rate = req_int(body, "base_rate_cents_per_unit", minimum=1)
    scenario = req_enum(body, "scenario", SCENARIOS)
    assume_rating = opt_enum(body, "assume_rating", ASSUME_RATINGS)
    assume_cleared = opt_str_list(body, "assume_cleared_category_codes")
    assume_removed = opt_int(body, "assume_removed_preventable_accidents", minimum=0)
    start = parse_datetime(period_start)
    end = parse_datetime(period_end)
    if end <= start:
        raise_error(ERR_INVALID_DATE_RANGE,
                    "policy_period_end must be later than policy_period_start")
    # Stage 4: existence
    carrier = require_ref("carriers", carrier_id, "carrier_id")
    # Stage 9: closed-interval overlap among DRAFT/QUOTED/BOUND
    _check_period_overlap(carrier_id, start, end)
    fields = {
        "base_rate_cents_per_unit": base_rate,
        "scenario": scenario,
        "assume_rating": assume_rating,
        "assume_cleared_category_codes": assume_cleared,
        "assume_removed_preventable_accidents": assume_removed,
    }
    computed = calc.compute_premium(fields, carrier)
    model = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "policy_period_start": period_start,
        "policy_period_end": period_end,
        "base_rate_cents_per_unit": base_rate,
        "scenario": scenario,
        "assume_rating": assume_rating,
        "assume_cleared_category_codes": assume_cleared,
        "assume_removed_preventable_accidents": assume_removed,
        "rating_factor_used": computed["rating_factor_used"],
        "score_loading_pct": computed["score_loading_pct"],
        "crash_loading_pct": computed["crash_loading_pct"],
        "driver_loading_pct": computed["driver_loading_pct"],
        "computed_premium_cents": computed["computed_premium_cents"],
        "carrier_version_at_compute": carrier["version"],
        "status": "DRAFT",
    })
    db["insurance_premium_models"][model["id"]] = model
    return success_object(public(model), 201)


@bp.get("/safety/insurance-premium-models")
def list_models():
    return list_response("insurance_premium_models", filters={
        "carrier_id": request.args.get("carrier_id"),
        "status": request.args.get("status"),
        "scenario": request.args.get("scenario"),
    })


@bp.get("/safety/insurance-premium-models/<rid>")
def get_model(rid):
    return get_one("insurance_premium_models", rid)


@bp.post("/safety/insurance-premium-models/<rid>/quote")
def quote(rid):
    authorized(ROLE)
    model = require_path_resource("insurance_premium_models", rid)
    if model["status"] != "DRAFT":
        raise_error(ERR_PREMIUM_MODEL_NOT_DRAFT, "quote requires DRAFT")
    carrier = db["carriers"].get(model["carrier_id"])
    if carrier is None or model["carrier_version_at_compute"] != carrier["version"]:
        raise_error(ERR_PREMIUM_INPUT_STALE,
                    "carrier inputs changed since the premium was computed")
    model["status"] = "QUOTED"
    touch(model)
    return success_object(public(model))


@bp.post("/safety/insurance-premium-models/<rid>/recompute")
def recompute(rid):
    authorized(ROLE)
    model = require_path_resource("insurance_premium_models", rid)
    if model["status"] not in ("STALE", "DRAFT"):
        raise_error(ERR_PREMIUM_MODEL_NOT_STALE, "recompute requires STALE or DRAFT")
    carrier = db["carriers"].get(model["carrier_id"])
    _check_period_overlap(
        model["carrier_id"],
        parse_datetime(model["policy_period_start"]),
        parse_datetime(model["policy_period_end"]),
        exclude_id=model["id"],
    )
    computed = calc.compute_premium(model, carrier)
    model["rating_factor_used"] = computed["rating_factor_used"]
    model["score_loading_pct"] = computed["score_loading_pct"]
    model["crash_loading_pct"] = computed["crash_loading_pct"]
    model["driver_loading_pct"] = computed["driver_loading_pct"]
    model["computed_premium_cents"] = computed["computed_premium_cents"]
    model["carrier_version_at_compute"] = carrier["version"]
    model["status"] = "DRAFT"
    touch(model)
    return success_object(public(model))


@bp.post("/safety/insurance-premium-models/<rid>/bind")
def bind(rid):
    authorized(ROLE)
    model = require_path_resource("insurance_premium_models", rid)
    if model["status"] != "QUOTED":
        raise_error(ERR_PREMIUM_MODEL_NOT_QUOTED, "bind requires QUOTED")
    carrier = db["carriers"].get(model["carrier_id"])
    if carrier is None or model["carrier_version_at_compute"] != carrier["version"]:
        raise_error(ERR_PREMIUM_INPUT_STALE,
                    "carrier inputs changed since the premium was computed")
    model["status"] = "BOUND"
    touch(model)
    return success_object(public(model))
