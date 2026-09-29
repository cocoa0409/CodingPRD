"""ConsumptionForecast endpoints (PRD 3.3)."""

from flask import Blueprint

import calc
import fetch
import serializers as ser
import validators as v
from db import db, now_iso, rows_in_order
from errors import fail
from middleware import (FUEL_ANALYST, HEDGE_ACCOUNTANT, RISK_POLICY_ADMIN,
                        TREASURY_RISK_MANAGER, endpoint, new_row, touch)
from response import created, ok, ok_list

bp = Blueprint("forecasts", __name__)

FORECAST_STATUSES = ("DRAFT", "PUBLISHED")


@bp.post("/fuel/consumption-forecasts")
@endpoint(FUEL_ANALYST)
def create_forecast():
    data = v.body()
    fleet = v.get_enum(data, "fleet_type", calc.FLEET_TYPES)
    route_group = v.get_enum(data, "route_group", calc.ROUTE_GROUPS)
    season = v.get_enum(data, "season", calc.SEASONS)
    start = v.get_month(data, "period_start_month")
    end = v.get_month(data, "period_end_month")
    gallons = v.get_number(data, "forecast_gallons", exclusive_minimum=0)

    if end <= start:
        fail("ERR_INVALID_REQUEST",
             "period_end_month must be strictly later than period_start_month.")

    row = new_row()
    row.update({
        "fleet_type": fleet,
        "route_group": route_group,
        "season": season,
        "period_start_month": start,
        "period_end_month": end,
        "forecast_gallons": gallons,
        "status": "DRAFT",
        "published_at": None,
    })
    db.forecasts[row["id"]] = row
    return created(ser.forecast(row))


@bp.get("/fuel/consumption-forecasts")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_forecasts():
    limit, offset = v.pagination()
    status = v.enum_filter("status", FORECAST_STATUSES)
    fleet = v.enum_filter("fleet_type", calc.FLEET_TYPES)
    route_group = v.enum_filter("route_group", calc.ROUTE_GROUPS)
    season = v.enum_filter("season", calc.SEASONS)

    rows = rows_in_order(db.forecasts)
    rows.sort(key=lambda r: (r["period_start_month"], r["_seq"]))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if fleet is not None:
        rows = [r for r in rows if r["fleet_type"] == fleet]
    if route_group is not None:
        rows = [r for r in rows if r["route_group"] == route_group]
    if season is not None:
        rows = [r for r in rows if r["season"] == season]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.forecast(r) for r in page], limit, offset, total)


@bp.post("/fuel/consumption-forecasts/<forecast_id>/publish")
@endpoint(FUEL_ANALYST)
def publish_forecast(forecast_id):
    row = fetch.forecast(forecast_id)

    if row["status"] != "DRAFT":
        fail("ERR_FORECAST_INVALID_STATE",
             "Only a DRAFT forecast may be published; this one is %s." % row["status"])

    for other in rows_in_order(db.forecasts):
        if other["id"] == row["id"] or other["status"] != "PUBLISHED":
            continue
        if other["fleet_type"] != row["fleet_type"]:
            continue
        if other["route_group"] != row["route_group"]:
            continue
        # Half-open [start, end) intervals: touching endpoints do not intersect.
        if row["period_start_month"] < other["period_end_month"] \
                and other["period_start_month"] < row["period_end_month"]:
            fail("ERR_FORECAST_PERIOD_OVERLAP",
                 "Month interval intersects a PUBLISHED forecast for the same fleet "
                 "type and route group.")

    row["status"] = "PUBLISHED"
    row["published_at"] = now_iso()
    touch(row)
    return ok(ser.forecast(row))
