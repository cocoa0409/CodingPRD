"""Season forecasts: two independent pre-season targets, always both stored."""

import re

from flask import Blueprint

import db
import response
from db import store, touch
from errors import invalid
from middleware import auth
from services import calc, derive, serialize
from util import (body, enum, filter_str, number, parse_iso, present, q2,
                  require, text, D)

bp = Blueprint("forecasts", __name__)

METHODS = ("SEVERITY_WEIGHTED", "TRAILING_BASELINE")
SEASON_CODE_RE = re.compile(r"^\d{4}-\d{2}$")


def _apply_targets(forecast):
    severity_weighted, trailing = calc.forecast_targets(forecast)
    forecast["target_tons_severity_weighted"] = severity_weighted
    forecast["target_tons_trailing_baseline"] = trailing
    forecast["binding_target_tons"] = (
        severity_weighted if forecast["method"] == "SEVERITY_WEIGHTED" else trailing)
    forecast["variant_spread_tons"] = q2(D(severity_weighted) - D(trailing))


@bp.post("/salt/season-forecasts")
@auth("ContractAdministrator", "LogisticsPlanner")
def create_forecast():
    payload = body()
    require(payload, ["season_code", "region_code", "normal_season_tons",
                      "severity_index", "prior_season_1_actual_tons",
                      "prior_season_2_actual_tons", "prior_season_3_actual_tons",
                      "method", "preseason_lock_date"])
    method = enum(payload, "method", METHODS)
    season_code = text(payload, "season_code", minlen=1, maxlen=20)
    if not SEASON_CODE_RE.match(season_code):
        invalid("season_code must look like 2026-27")
    region_code = text(payload, "region_code", minlen=1, maxlen=30)
    normal = number(payload, "normal_season_tons", gt=0)
    severity = number(payload, "severity_index", minv=0, maxv=100, integer=True)
    p1 = number(payload, "prior_season_1_actual_tons", minv=0)
    p2 = number(payload, "prior_season_2_actual_tons", minv=0)
    p3 = number(payload, "prior_season_3_actual_tons", minv=0)
    lock_date = parse_iso(payload["preseason_lock_date"], "preseason_lock_date")

    for peer in store.forecasts.values():
        if peer["season_code"] == season_code and peer["region_code"] == region_code:
            invalid("season_code %s already exists for region %s"
                    % (season_code, region_code))

    forecast = db.stamp()
    forecast.update({
        "season_code": season_code,
        "region_code": region_code,
        "normal_season_tons": normal,
        "severity_index": severity,
        "prior_season_1_actual_tons": p1,
        "prior_season_2_actual_tons": p2,
        "prior_season_3_actual_tons": p3,
        "method": method,
        "preseason_lock_date": lock_date,
    })
    _apply_targets(forecast)
    store.forecasts[forecast["id"]] = forecast
    return response.created(serialize.forecast_json(forecast))


@bp.get("/salt/season-forecasts/<forecast_id>")
@auth()
def read_forecast(forecast_id):
    return response.ok(serialize.forecast_json(derive.get_forecast(forecast_id)))


@bp.get("/salt/season-forecasts")
@auth()
def list_forecasts():
    rows = list(store.forecasts.values())
    for name in ("season_code", "region_code", "method"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return response.page(db.by_seq(rows), serialize.forecast_json)


@bp.patch("/salt/season-forecasts/<forecast_id>")
@auth("ContractAdministrator")
def patch_forecast(forecast_id):
    payload = body()
    severity = number(payload, "severity_index", minv=0, maxv=100, integer=True,
                      required=False)
    method = enum(payload, "method", METHODS, required=False)
    lock_date = None
    if present(payload, "preseason_lock_date"):
        lock_date = parse_iso(payload["preseason_lock_date"], "preseason_lock_date")

    forecast = derive.get_forecast(forecast_id)
    if severity is not None:
        forecast["severity_index"] = severity
    if method is not None:
        forecast["method"] = method
    if lock_date is not None:
        forecast["preseason_lock_date"] = lock_date

    _apply_targets(forecast)
    touch(forecast)
    return response.ok(serialize.forecast_json(forecast))
