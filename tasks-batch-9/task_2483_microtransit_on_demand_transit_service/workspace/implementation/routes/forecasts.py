"""Demand forecasts and peak-surge fleet sizing (PRD Section 3.3)."""
from flask import Blueprint

import calculations as calc
import clock
import db
import listing
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint

bp = Blueprint("forecasts", __name__)

CONFIGURABLE_ZONE_STATES = ("DRAFT", "ACTIVE")


def get_forecast(forecast_id):
    forecast = db.demand_forecasts.get(forecast_id)
    if forecast is None:
        raise ApiError("ERR_DEMAND_FORECAST_NOT_FOUND")
    return forecast


@bp.post("/demand-forecasts")
@endpoint(["ZoneAdmin"])
def create_forecast():
    body = validation.get_body()

    zone_raw = validation.raw_fk(body, "zone_id")
    zone = db.service_zones.get(zone_raw) if zone_raw is not None else None
    if zone_raw is not None and zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")

    zone_id = validation.req_str(body, "zone_id")
    start_raw, start_dt = validation.req_datetime(body, "window_start_utc")
    end_raw, end_dt = validation.req_datetime(body, "window_end_utc")
    forecast_trips = validation.req_int(body, "forecast_trips", 0)
    peak_factor = validation.req_number(body, "peak_factor", 1.00, 4.00, max_dp=2)
    expected_version = validation.req_int(body, "expected_service_zone_version")
    if end_dt <= start_dt:
        validation.invalid("window_end_utc must be later than window_start_utc.")
    if zone is None:
        zone = db.service_zones.get(zone_id)
        if zone is None:
            raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")

    if zone["status"] not in CONFIGURABLE_ZONE_STATES:
        raise ApiError("ERR_ZONE_NOT_ACTIVE")

    if expected_version != zone["version"]:
        raise ApiError("ERR_STALE_SERVICE_ZONE_VERSION")

    base_blocks, surge_blocks = calc.fleet_sizing(
        start_dt, end_dt, forecast_trips, peak_factor)

    # supersede-on-create: every overlapping PUBLISHED forecast of this zone
    superseded = []
    for other in db.demand_forecasts.values():
        if other["zone_id"] != zone["id"] or other["state"] != "PUBLISHED":
            continue
        other_start = clock.parse_dt(other["window_start_utc"])
        other_end = clock.parse_dt(other["window_end_utc"])
        if calc.overlaps_half_open(other_start, other_end, start_dt, end_dt):
            superseded.append(other)
    for other in db.by_created_at(superseded):
        other["state"] = "SUPERSEDED"
        db.touch(other)

    forecast = db.base_record()
    forecast.update({
        "zone_id": zone["id"],
        "window_start_utc": start_raw,
        "window_end_utc": end_raw,
        "forecast_trips": forecast_trips,
        "peak_factor": peak_factor,
        "required_base_blocks": base_blocks,
        "required_surge_blocks": surge_blocks,
        "state": "PUBLISHED",
    })
    db.demand_forecasts.add(forecast)

    db.touch(zone)
    return response.created(
        serializers.pick(forecast, serializers.DEMAND_FORECAST))


@bp.get("/demand-forecasts/<forecast_id>")
@endpoint(ALL_ROLES)
def read_forecast(forecast_id):
    forecast = get_forecast(forecast_id)
    return response.object_response(
        serializers.pick(forecast, serializers.DEMAND_FORECAST))


@bp.get("/demand-forecasts")
@endpoint(ALL_ROLES)
def list_forecasts():
    return listing.list_endpoint(
        db.demand_forecasts.ordered(), serializers.DEMAND_FORECAST,
        {"zone_id": "zone_id", "state": "state"})
