"""Weather station, observation and fire-potential-index endpoints."""

from flask import Blueprint

import db
import validation as v
from middleware import (
    ASSET_INSPECTOR,
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import list_response, object_response
from services import calc

bp = Blueprint("weather", __name__)

TELEMETRY_STATUSES = ("ONLINE", "DEGRADED", "OFFLINE")
READ_ROLES = (
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)


@bp.post("/weather-stations")
@roles(GRID_PLANNER, METEOROLOGY_ANALYST)
def create_station():
    body = v.Body()
    station_code = body.string("station_code", 3, 40)
    circuit_id = body.string("circuit_id", 1, None)
    elevation_ft = body.number("elevation_ft", minimum=-300, maximum=15000)
    weight = body.number(
        "representativeness_weight", exclusive_minimum=0, maximum=1, max_decimals=2
    )
    telemetry_status = body.enum(
        "telemetry_status", TELEMETRY_STATUSES, required=False, default="ONLINE"
    )

    circuit = v.circuit(circuit_id)
    v.unique_code(db.weather_stations, "station_code", station_code)

    row = db.new_row()
    row["station_code"] = station_code
    row["circuit_id"] = circuit["id"]
    row["elevation_ft"] = elevation_ft
    row["representativeness_weight"] = weight
    row["telemetry_status"] = telemetry_status
    row["observation_count"] = 0
    db.set_dt(row, "last_observation_at", None)
    db.weather_stations[row["id"]] = row
    return object_response(db.weather_station_out(row), 201)


@bp.get("/weather-stations/<station_id>")
@roles(*READ_ROLES)
def get_station(station_id):
    return object_response(db.weather_station_out(v.weather_station(station_id)))


@bp.get("/weather-stations/<station_id>/observations")
@roles(*READ_ROLES)
def list_observations(station_id):
    station = v.weather_station(station_id)
    limit, offset = v.pagination()
    rows = [
        o
        for o in db.weather_observations.values()
        if o["weather_station_id"] == station["id"]
    ]
    rows.sort(key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))
    total = len(rows)
    window = rows[offset : offset + limit]
    return list_response(
        [db.weather_observation_out(r) for r in window], limit, offset, total
    )


@bp.post("/weather-observations")
@roles(METEOROLOGY_ANALYST)
def create_observation():
    body = v.Body()
    station_id = body.string("weather_station_id", 1, None)
    observed_at, observed_at_raw = body.timestamp("observed_at")
    wind_gust = body.number("wind_gust_mph", minimum=0, maximum=200, max_decimals=1)
    humidity = body.number("relative_humidity_pct", minimum=0, maximum=100, max_decimals=1)
    temperature = body.number("temperature_f", minimum=-40, maximum=140, max_decimals=1)
    fuel = body.number("dead_fuel_moisture_pct", minimum=0, maximum=60, max_decimals=1)

    station = v.weather_station(station_id)

    row = db.new_row(versioned=False)
    row["weather_station_id"] = station["id"]
    db.set_dt(row, "observed_at", observed_at, observed_at_raw)
    row["wind_gust_mph"] = wind_gust
    row["relative_humidity_pct"] = humidity
    row["temperature_f"] = temperature
    row["dead_fuel_moisture_pct"] = fuel
    db.weather_observations[row["id"]] = row

    observations = [
        o
        for o in db.weather_observations.values()
        if o["weather_station_id"] == station["id"]
    ]
    station["observation_count"] = len(observations)
    latest = max(observations, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))
    db.set_dt(
        station,
        "last_observation_at",
        latest["observed_at"],
        latest.get("_raw", {}).get("observed_at"),
    )
    db.touch(station)

    return object_response(db.weather_observation_out(row), 201)


@bp.post("/fire-potential-indices")
@roles(METEOROLOGY_ANALYST)
def create_index():
    body = v.Body()
    circuit_id = body.string("circuit_id", 1, None)
    forecast_date = body.date("forecast_date")
    variant = body.enum("computation_variant", ("FORECAST", "VALIDATED"))

    circuit = v.circuit(circuit_id)

    computed = calc.compute_fire_potential_index(circuit, forecast_date, variant)

    row = db.new_row(versioned=False)
    row["circuit_id"] = circuit["id"]
    row["forecast_date"] = forecast_date
    row["computation_variant"] = variant
    row.update(computed)
    db.fire_potential_indices[row["id"]] = row

    if variant == "FORECAST":
        before = (
            circuit["risk_posture"],
            circuit["latest_forecast_fpi_score"],
            circuit["latest_forecast_fpi_tier"],
        )
        calc.recompute_risk_posture(circuit)
        after = (
            circuit["risk_posture"],
            circuit["latest_forecast_fpi_score"],
            circuit["latest_forecast_fpi_tier"],
        )
        if before != after:
            db.touch(circuit)

    return object_response(db.fire_potential_index_out(row), 201)
