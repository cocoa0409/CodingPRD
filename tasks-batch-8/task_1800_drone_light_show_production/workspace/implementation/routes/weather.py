"""WeatherReading endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at, clock_now, parse_dt, fmt_dt
from middleware import require_role, get_auth
from response import success_object, success_list
from services.show import serialize_weather_reading

bp = Blueprint("weather", __name__)


@bp.route("/api/weather-readings", methods=["POST"])
def create_weather_reading():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["site_id", "recorded_at", "wind_speed_kt", "gust_kt",
                        "precip_mm_hr", "temperature_c"])
    require_role("SafetyOfficer")
    site_id = body["site_id"]
    if not isinstance(site_id, str):
        raise errors.validation("site_id must be a string")
    recorded_raw, recorded = V.req_dt(body, "recorded_at")
    wind = V.req_number(body, "wind_speed_kt")
    gust = V.req_number(body, "gust_kt")
    precip = V.req_number(body, "precip_mm_hr")
    temp = V.req_number(body, "temperature_c")
    if wind < 0:
        raise errors.validation("wind_speed_kt must be >= 0")
    if gust < 0:
        raise errors.validation("gust_kt must be >= 0")
    if gust < wind:
        raise errors.validation("gust_kt must be >= wind_speed_kt")
    if precip < 0:
        raise errors.validation("precip_mm_hr must be >= 0")

    site = DB.sites.get(site_id)
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")

    if recorded > clock_now():
        raise errors.conflict("ERR_READING_IN_FUTURE", "recorded_at is after the logical clock")

    rid = new_id()
    ts = wall_created_at()
    reading = {
        "id": rid, "site_id": site_id,
        "recorded_at": recorded_raw,
        "wind_speed_kt": wind, "gust_kt": gust,
        "precip_mm_hr": precip, "temperature_c": temp,
        "created_at": ts,
    }
    DB.weather_readings[rid] = reading
    DB.insertion_order["weather_readings"].append(rid)
    return success_object(serialize_weather_reading(reading), 201)


@bp.route("/api/weather-readings/<weatherReadingId>", methods=["GET"])
def get_weather_reading(weatherReadingId):
    get_auth()
    r = DB.weather_readings.get(weatherReadingId)
    if r is None:
        raise errors.not_found("ERR_WEATHER_READING_NOT_FOUND", "weather reading not found")
    return success_object(serialize_weather_reading(r))


@bp.route("/api/weather-readings", methods=["GET"])
def list_weather_readings():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    site_id = V.opt_string(request.args, "site_id")
    items = [DB.weather_readings[i] for i in DB.insertion_order["weather_readings"]]
    if site_id is not None:
        items = [r for r in items if r["site_id"] == site_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_weather_reading(r) for r in page], limit, offset, total)
