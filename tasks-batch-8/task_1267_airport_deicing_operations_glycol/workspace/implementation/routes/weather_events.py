"""Weather event routes: create, get, list, activate, end, escalate."""
from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc

bp = Blueprint("weather_events", __name__)

PRECIP_TYPES = {"SNOW", "FREEZING_FOG", "FREEZING_RAIN", "MIXED"}
PRECIP_RATES = {"LIGHT", "MODERATE", "HEAVY"}
SEVERITIES = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}


def _staffing_status(event):
    return "ADEQUATE" if event["assigned_crew_count"] >= event["required_crew_count"] else "SHORT"


@bp.route("/deice-ops/weather-events", methods=["POST"])
def create_weather_event():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["station_id", "precip_type", "precip_rate", "severity", "started_at"])
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    precip_type = util.require_enum(payload["precip_type"], PRECIP_TYPES, "precip_type")
    precip_rate = util.require_enum(payload["precip_rate"], PRECIP_RATES, "precip_rate")
    severity = util.require_enum(payload["severity"], SEVERITIES, "severity")
    started_dt = util.parse_iso(payload["started_at"], "started_at")
    now = util.iso_now()
    event = {
        "id": util.new_id(),
        "station_id": station["id"],
        "precip_type": precip_type,
        "precip_rate": precip_rate,
        "severity": severity,
        "started_at": payload["started_at"],
        "ended_at": None,
        "required_crew_count": calc.REQUIRED_CREW[severity],
        "assigned_crew_count": 0,
        "staffing_status": "SHORT",
        "escalation_level": 0,
        "status": "FORECASTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    event["_created_dt"] = db.get_clock()
    event["_started_dt"] = started_dt
    db.weather_events[event["id"]] = event
    return response.success_object(serializers.weather_event(event), 201)


@bp.route("/deice-ops/weather-events/<eid>", methods=["GET"])
def get_weather_event(eid):
    middleware.require_roles("StationAdmin", "PadOperator", "EnvironmentalOfficer")
    event = db.weather_events.get(eid)
    if event is None:
        raise errors.not_found("weather event not found")
    return response.success_object(serializers.weather_event(event), 200)


@bp.route("/deice-ops/weather-events", methods=["GET"])
def list_weather_events():
    middleware.require_roles("StationAdmin", "PadOperator", "EnvironmentalOfficer")
    limit, offset = util.get_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = list(db.weather_events.values())
    if station_id is not None:
        items = [e for e in items if e["station_id"] == station_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.weather_event(e) for e in page], limit, offset, total)


@bp.route("/deice-ops/weather-events/<eid>/activate", methods=["POST"])
def activate_weather_event(eid):
    middleware.require_roles("StationAdmin")
    event = db.weather_events.get(eid)
    if event is None:
        raise errors.not_found("weather event not found")
    if event["status"] not in ("FORECASTED", "ENDED"):
        raise errors.invalid_state("event must be FORECASTED or ENDED to activate")
    event["status"] = "ACTIVE"
    event["ended_at"] = None
    event["version"] += 1
    event["updated_at"] = util.iso_now()
    return response.success_object(serializers.weather_event(event), 200)


@bp.route("/deice-ops/weather-events/<eid>/end", methods=["POST"])
def end_weather_event(eid):
    middleware.require_roles("StationAdmin")
    event = db.weather_events.get(eid)
    if event is None:
        raise errors.not_found("weather event not found")
    now = util.iso_now()
    if event["status"] == "ACTIVE":
        event["status"] = "ENDED"
    elif event["status"] == "FORECASTED":
        event["status"] = "CANCELLED"
    else:
        raise errors.invalid_state("event must be ACTIVE or FORECASTED to end")
    event["ended_at"] = now
    event["version"] += 1
    event["updated_at"] = now
    return response.success_object(serializers.weather_event(event), 200)


@bp.route("/deice-ops/weather-events/<eid>/escalate", methods=["POST"])
def escalate_weather_event(eid):
    middleware.require_roles("StationAdmin")
    event = db.weather_events.get(eid)
    if event is None:
        raise errors.not_found("weather event not found")
    if event["status"] in ("ENDED", "CANCELLED"):
        raise errors.invalid_state("cannot escalate an ended or cancelled event")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["assigned_crew_count"])
    count = util.to_int(payload["assigned_crew_count"], "assigned_crew_count")
    if count < 0:
        raise errors.invalid_request("assigned_crew_count must be >= 0")
    event["assigned_crew_count"] = count
    event["escalation_level"] = event.get("escalation_level", 0) + 1
    event["staffing_status"] = _staffing_status(event)
    event["version"] += 1
    event["updated_at"] = util.iso_now()
    return response.success_object(serializers.weather_event(event), 200)
