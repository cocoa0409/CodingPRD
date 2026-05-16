"""SessionDay (weather) routes."""

from flask import Blueprint

from config import ROLE_GUARDIAN, ROLE_PROGRAM_ADMIN, WEATHER_STATUSES
from errors import APIError
from middleware import get_json_body, require_auth
from response import success_response
from services.lookups import get_session_day
from services.serializers import serialize_session_day
from services.sessions import reroute_preview, set_weather
from services.validators import require_enum


weather_bp = Blueprint("weather", __name__)


@weather_bp.route("/session-days/<session_day_id>", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN, ROLE_GUARDIAN})
def read_session_day(session_day_id):
    sd = get_session_day(session_day_id)
    return success_response(serialize_session_day(sd))


@weather_bp.route("/session-days/<session_day_id>/set-weather", methods=["POST"])
@require_auth({ROLE_PROGRAM_ADMIN})
def set_weather_route(session_day_id):
    sd = get_session_day(session_day_id)
    body = get_json_body()
    new_weather = require_enum(body, "weather_status", WEATHER_STATUSES)
    set_weather(sd, new_weather)
    return success_response(serialize_session_day(sd))


@weather_bp.route("/session-days/<session_day_id>/reroute-preview", methods=["GET"])
@require_auth({ROLE_PROGRAM_ADMIN})
def reroute_preview_route(session_day_id):
    sd = get_session_day(session_day_id)
    data, overflow_present = reroute_preview(sd)
    if overflow_present:
        # Diagnostic — pool is insufficient
        raise APIError("ERR_RAINY_POOL_EXHAUSTED")
    return success_response(data)
