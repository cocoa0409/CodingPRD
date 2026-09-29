"""CommercializationForecast, DisclosureGrant and logical-clock endpoints."""

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, set_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import cascade, ledger
from validate import (as_datetime, as_enum, as_int, as_str, body_json, require)

bp = Blueprint("commercial", __name__)


# --- CommercializationForecast ----------------------------------------------

@bp.post("/commercialization-forecasts")
def create_forecast():
    auth(["AccountManager"])
    body = body_json()
    brief_id = as_str(require(body, "brief_id"), "brief_id")
    annual_volume_kg = as_int(require(body, "annual_volume_kg"),
                              "annual_volume_kg", minimum=1)
    unit_price = as_int(require(body, "unit_price_cents_per_kg"),
                        "unit_price_cents_per_kg", minimum=1)
    expected = as_int(require(body, "expected_brief_version"),
                      "expected_brief_version", minimum=1)

    brief = need(db.briefs, brief_id, "ERR_BRIEF_NOT_FOUND", "customer brief")
    if expected != brief["version"]:
        fail("ERR_STALE_BRIEF_VERSION",
             "expected_brief_version %s does not match the current version %s"
             % (expected, brief["version"]))

    superseded = [f for f in ledger.forecasts_of_brief(brief["id"])
                  if f["status"] in ("ACTIVE", "AT_RISK")]

    forecast = base_entity()
    forecast.update({
        "brief_id": brief["id"],
        "annual_volume_kg": annual_volume_kg,
        "unit_price_cents_per_kg": unit_price,
        "pinned_brief_version": expected,
        "variant_applied": None,
        "stage_probability": None,
        "technical_factor": None,
        "weighted_annual_value_cents": None,
        "status": "ACTIVE",
    })
    cascade.revalue_forecast(forecast, brief)
    db.forecasts[forecast["id"]] = forecast

    for prior in superseded:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    return created(S.forecast_out(forecast))


@bp.get("/commercialization-forecasts")
def list_forecasts():
    auth(ALL_ROLES)
    brief_id = request.args.get("brief_id")
    status = request.args.get("status")
    rows = []
    for forecast in db.forecasts.values():
        if brief_id is not None and forecast["brief_id"] != brief_id:
            continue
        if status is not None and forecast["status"] != status:
            continue
        rows.append(forecast)
    return list_response(rows, S.forecast_out)


@bp.get("/commercialization-forecasts/<forecast_id>")
def get_forecast(forecast_id):
    auth(ALL_ROLES)
    forecast = need(db.forecasts, forecast_id, "ERR_FORECAST_NOT_FOUND",
                    "commercialization forecast")
    return ok(S.forecast_out(forecast))


# --- DisclosureGrant --------------------------------------------------------

@bp.post("/disclosure-grants")
def create_grant():
    auth(["TechnicalDirector"])
    body = body_json()
    brief_id = as_str(require(body, "brief_id"), "brief_id")
    formula_id = as_str(require(body, "formula_id"), "formula_id")
    disclosed_tier = as_enum(require(body, "disclosed_tier"), "disclosed_tier",
                             K.TIERS)
    redaction_level = as_enum(require(body, "redaction_level"),
                              "redaction_level", K.REDACTION_LEVELS)
    expires_at = as_datetime(require(body, "expires_at"), "expires_at")

    brief = need(db.briefs, brief_id, "ERR_BRIEF_NOT_FOUND", "customer brief")
    formula = need(db.formulas, formula_id, "ERR_FORMULA_NOT_FOUND", "formula")

    if not expires_at > now_logical():
        fail("ERR_INVALID_INTERVAL",
             "expires_at must be strictly after the current logical clock")
    if formula["brief_id"] != brief["id"]:
        fail("ERR_GRANT_FORMULA_MISMATCH",
             "the formula does not belong to the named brief")

    grant = base_entity()
    grant.update({
        "brief_id": brief["id"],
        "formula_id": formula["id"],
        "disclosed_tier": disclosed_tier,
        "redaction_level": redaction_level,
        "expires_at": expires_at,
    })
    db.grants[grant["id"]] = grant
    return created(S.grant_out(grant))


@bp.get("/disclosure-grants")
def list_grants():
    auth(ALL_ROLES)
    brief_id = request.args.get("brief_id")
    formula_id = request.args.get("formula_id")
    rows = []
    for grant in db.grants.values():
        if brief_id is not None and grant["brief_id"] != brief_id:
            continue
        if formula_id is not None and grant["formula_id"] != formula_id:
            continue
        rows.append(grant)
    return list_response(rows, S.grant_out)


@bp.get("/disclosure-grants/<grant_id>")
def get_grant(grant_id):
    auth(ALL_ROLES)
    grant = need(db.grants, grant_id, "ERR_GRANT_NOT_FOUND", "disclosure grant")
    return ok(S.grant_out(grant))


# --- logical clock ----------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(ALL_ROLES)
    body = body_json()
    current_utc = as_datetime(require(body, "current_utc"), "current_utc")
    set_logical(current_utc)
    return ok({})
