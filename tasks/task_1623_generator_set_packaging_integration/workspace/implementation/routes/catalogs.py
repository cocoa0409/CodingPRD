"""EngineModel and AlternatorModel endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("catalogs", __name__)

VALID_TIERS = {"TIER_2", "EPA_TIER_4", "STAGE_V", "TIER_4_FINAL_CARB"}
VALID_ENGINE_STATUSES = {"ACTIVE", "DISCONTINUED"}


# --- EngineModel -----------------------------------------------------------

@bp.route("/genset-packaging/engine-models", methods=["POST"])
def create_engine_model():
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()

    record = {
        "model_code": mw.require_string(body, "model_code"),
        "manufacturer": mw.require_string(body, "manufacturer"),
        "rated_kw": mw.require_int(body, "rated_kw", minimum=1),
        "fuel_burn_gph_at_75": mw.require_number(body, "fuel_burn_gph_at_75", minimum=0, exclusive_minimum=True),
        "emissions_tier_capability": mw.require_enum(body, "emissions_tier_capability", VALID_TIERS),
        "list_price_cents": mw.require_int(body, "list_price_cents", minimum=0),
        "status": mw.optional_enum(body, "status", VALID_ENGINE_STATUSES, "ACTIVE"),
    }
    db.stamp_new(record)
    db.engine_models[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/engine-models/<engineModelId>", methods=["GET"])
def get_engine_model(engineModelId):
    mw.authenticate()
    record = db.engine_models.get(engineModelId)
    if record is None:
        raise errors.not_found("Engine model not found")
    return resp.success_object(record)


# --- AlternatorModel -------------------------------------------------------

@bp.route("/genset-packaging/alternator-models", methods=["POST"])
def create_alternator_model():
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()

    record = {
        "model_code": mw.require_string(body, "model_code"),
        "rated_kva": mw.require_int(body, "rated_kva", minimum=1),
        "efficiency_pct": mw.require_number(body, "efficiency_pct", minimum=0, maximum=100, exclusive_minimum=True),
        "list_price_cents": mw.require_int(body, "list_price_cents", minimum=0),
    }
    db.stamp_new(record)
    db.alternator_models[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/alternator-models/<alternatorModelId>", methods=["GET"])
def get_alternator_model(alternatorModelId):
    mw.authenticate()
    record = db.alternator_models.get(alternatorModelId)
    if record is None:
        raise errors.not_found("Alternator model not found")
    return resp.success_object(record)
