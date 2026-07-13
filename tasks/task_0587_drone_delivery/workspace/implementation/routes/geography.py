"""Service areas, nests, geofence zones and weather (PRD 3.1)."""
from flask import Blueprint

import calc
import serializers
import validation as v
from auth import require
from db import db, get_or_404, new_record, touch
from response import ok
from routes import filtered, list_response

bp = Blueprint("geography", __name__)

ALL_ROLES = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "MaintenanceTech", "Customer")
STAFF = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "MaintenanceTech")


# --- service areas --------------------------------------------------------


@bp.post("/service-areas")
@require("PlatformAdmin")
def create_service_area():
    body = v.body()
    rec = new_record(
        "ServiceArea",
        {
            "name": v.as_string(body, "name"),
            "center_lat": v.as_number(body, "center_lat"),
            "center_lon": v.as_number(body, "center_lon"),
            "max_range_km": v.as_number(body, "max_range_km", gt=0),
            "max_payload_g": v.as_integer(body, "max_payload_g", gt=0),
            "status": "ACTIVE",
        },
    )
    return ok(serializers.service_area(rec), 201)


@bp.get("/service-areas/<area_id>")
@require(*ALL_ROLES)
def read_service_area(area_id):
    return ok(serializers.service_area(get_or_404("ServiceArea", area_id)))


@bp.post("/service-areas/<area_id>/suspend")
@require("PlatformAdmin", "FlightDirector")
def suspend_service_area(area_id):
    area = get_or_404("ServiceArea", area_id)
    area["status"] = "SUSPENDED"
    touch(area)
    return ok(serializers.service_area(area))


# --- nests ----------------------------------------------------------------


@bp.post("/nests")
@require("PlatformAdmin")
def create_nest():
    body = v.body()
    service_area_id = v.as_string(body, "service_area_id")
    name = v.as_string(body, "name")
    lat = v.as_number(body, "lat")
    lon = v.as_number(body, "lon")
    pad_count = v.as_integer(body, "pad_count", gte=1)
    status = v.as_enum(body, "status", ("OPEN", "CLOSED"), required=False, default="OPEN")

    get_or_404("ServiceArea", service_area_id)
    rec = new_record(
        "Nest",
        {
            "service_area_id": service_area_id,
            "name": name,
            "lat": lat,
            "lon": lon,
            "pad_count": pad_count,
            "status": status,
        },
    )
    return ok(serializers.nest(rec), 201)


@bp.get("/nests")
@require(*STAFF)
def list_nests():
    limit, offset = v.pagination()
    rows = filtered(
        db.nests.values(),
        service_area_id=v.query_str("service_area_id"),
        status=v.query_enum("status", ("OPEN", "CLOSED")),
    )
    return list_response(rows, serializers.nest, limit, offset)


@bp.get("/nests/<nest_id>")
@require(*STAFF)
def read_nest(nest_id):
    return ok(serializers.nest(get_or_404("Nest", nest_id)))


# --- geofence zones -------------------------------------------------------

ZONE_ROLES = ("PlatformAdmin", "DispatchOperator", "FlightDirector")


@bp.post("/geofence-zones")
@require("PlatformAdmin", "FlightDirector")
def create_zone():
    body = v.body()
    service_area_id = v.as_string(body, "service_area_id")
    kind = v.as_enum(body, "kind", ("NO_FLY", "TFR", "WEATHER_HOLD"))
    center_lat = v.as_number(body, "center_lat")
    center_lon = v.as_number(body, "center_lon")
    radius_km = v.as_number(body, "radius_km", gt=0)
    effective_from = v.as_datetime(body, "effective_from")
    effective_to = v.as_datetime(body, "effective_to")

    get_or_404("ServiceArea", service_area_id)
    rec = new_record(
        "GeofenceZone",
        {
            "service_area_id": service_area_id,
            "kind": kind,
            "center_lat": center_lat,
            "center_lon": center_lon,
            "radius_km": radius_km,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
        },
    )
    return ok(serializers.geofence_zone(rec), 201)


@bp.get("/geofence-zones")
@require(*ZONE_ROLES)
def list_zones():
    limit, offset = v.pagination()
    rows = filtered(
        db.geofence_zones.values(),
        service_area_id=v.query_str("service_area_id"),
        status=v.query_enum("status", ("ACTIVE", "LIFTED")),
    )
    return list_response(rows, serializers.geofence_zone, limit, offset)


@bp.get("/geofence-zones/<zone_id>")
@require(*ZONE_ROLES)
def read_zone(zone_id):
    return ok(serializers.geofence_zone(get_or_404("GeofenceZone", zone_id)))


@bp.post("/geofence-zones/<zone_id>/lift")
@require("PlatformAdmin", "FlightDirector")
def lift_zone(zone_id):
    zone = get_or_404("GeofenceZone", zone_id)
    zone["status"] = "LIFTED"
    touch(zone)
    return ok(serializers.geofence_zone(zone))


# --- weather --------------------------------------------------------------


@bp.post("/weather-observations")
@require("PlatformAdmin", "DispatchOperator")
def create_observation():
    body = v.body()
    service_area_id = v.as_string(body, "service_area_id")
    observed_at = v.as_datetime(body, "observed_at")
    wind_kph = v.as_number(body, "wind_kph", gte=0)
    gust_kph = v.as_number(body, "gust_kph", gte=0)
    visibility_km = v.as_number(body, "visibility_km", gte=0)
    precip = v.as_enum(body, "precip", ("NONE", "LIGHT", "HEAVY"), required=False, default="NONE")

    get_or_404("ServiceArea", service_area_id)
    rec = new_record(
        "WeatherObservation",
        {
            "service_area_id": service_area_id,
            "observed_at": observed_at,
            "wind_kph": wind_kph,
            "gust_kph": gust_kph,
            "visibility_km": visibility_km,
            "precip": precip,
            "flyable": calc.flyable(wind_kph, gust_kph, visibility_km, precip),
        },
        versioned=False,
    )
    return ok(serializers.weather_observation(rec), 201)


@bp.get("/weather-observations")
@require(*ZONE_ROLES)
def list_observations():
    limit, offset = v.pagination()
    rows = filtered(db.weather_observations.values(), service_area_id=v.query_str("service_area_id"))
    return list_response(rows, serializers.weather_observation, limit, offset)


@bp.get("/weather-observations/<obs_id>")
@require(*ZONE_ROLES)
def read_observation(obs_id):
    return ok(serializers.weather_observation(get_or_404("WeatherObservation", obs_id)))
