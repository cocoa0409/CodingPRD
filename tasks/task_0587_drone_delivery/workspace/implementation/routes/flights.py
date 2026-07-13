"""The sortie: filing, release, launch, arrival, drop, recovery and abort (PRD 3.5-3.7)."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import serializers
import validation as v
from auth import require
from db import db, get_or_404, new_record, touch
from errors import err
from response import ok
from routes import filtered, list_response
from services import flight_service

bp = Blueprint("flights", __name__)

STAFF = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "MaintenanceTech")
DROP_READERS = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "Customer")
AUTH_READERS = ("PlatformAdmin", "DispatchOperator", "FlightDirector")
OPS_STATES = ("PLANNED", "LAUNCHED", "DROPPING", "RETURNING", "RECOVERED", "ABORTED")
AUTH_STATUSES = ("PENDING", "APPROVED", "DENIED", "REVOKED")


# --- reads ----------------------------------------------------------------


@bp.get("/flights")
@require(*STAFF)
def list_flights():
    limit, offset = v.pagination()
    rows = filtered(
        db.flights.values(),
        order_id=v.query_str("order_id"),
        drone_id=v.query_str("drone_id"),
        launch_nest_id=v.query_str("launch_nest_id"),
        recovery_nest_id=v.query_str("recovery_nest_id"),
        battery_id=v.query_str("battery_id"),
        ops_state=v.query_enum("ops_state", OPS_STATES),
    )
    return list_response(rows, serializers.flight, limit, offset)


@bp.get("/flights/<flight_id>")
@require(*STAFF)
def read_flight(flight_id):
    return ok(serializers.flight(get_or_404("Flight", flight_id)))


@bp.get("/flights/<flight_id>/delivery-drops")
@require(*DROP_READERS)
def list_flight_drops(flight_id):
    limit, offset = v.pagination()
    flight = get_or_404("Flight", flight_id)
    rows = [d for d in db.delivery_drops.values() if d["flight_id"] == flight["id"]]
    return list_response(rows, serializers.delivery_drop, limit, offset)


@bp.get("/delivery-drops/<drop_id>")
@require(*DROP_READERS)
def read_drop(drop_id):
    return ok(serializers.delivery_drop(get_or_404("DeliveryDrop", drop_id)))


@bp.get("/airspace-authorizations")
@require(*AUTH_READERS)
def list_authorizations():
    limit, offset = v.pagination()
    rows = filtered(
        db.authorizations.values(),
        flight_id=v.query_str("flight_id"),
        status=v.query_enum("status", AUTH_STATUSES),
    )
    return list_response(rows, serializers.authorization, limit, offset)


@bp.get("/airspace-authorizations/<auth_id>")
@require(*AUTH_READERS)
def read_authorization(auth_id):
    return ok(serializers.authorization(get_or_404("AirspaceAuthorization", auth_id)))


# --- the regulatory track (PRD 3.5) --------------------------------------


@bp.post("/flights/<flight_id>/file-authorization")
@require("DispatchOperator")
def file_authorization(flight_id):
    body = v.body()
    grid_cells = v.as_string_list(body, "grid_cells")
    requested_alt_ft = v.as_integer(body, "requested_alt_ft", gt=0, lte=400)
    window_start = v.as_datetime(body, "window_start")
    window_end = v.as_datetime(body, "window_end")

    flight = get_or_404("Flight", flight_id)
    if flight["ops_state"] != "PLANNED":
        raise err("ERR_FLIGHT_NOT_PLANNED")
    if flight["clearance_state"] != "UNFILED":
        raise err("ERR_FLIGHT_NOT_CLEARED", "The sortie's airspace request has already been filed.")

    auth = new_record(
        "AirspaceAuthorization",
        {
            "flight_id": flight["id"],
            "grid_cells": grid_cells,
            "requested_alt_ft": requested_alt_ft,
            "window_start": window_start,
            "window_end": window_end,
            "status": "PENDING",
            "auth_code": None,
        },
    )

    flight["clearance_state"] = "FILED"
    flight["filed_by_user_id"] = g.user_id
    touch(flight)
    return ok(serializers.authorization(auth), 201)


@bp.post("/flights/<flight_id>/release")
@require("FlightDirector")
def release_flight(flight_id):
    flight = get_or_404("Flight", flight_id)

    if flight["clearance_state"] != "FILED":
        raise err("ERR_FLIGHT_NOT_CLEARED")
    if flight["ops_state"] != "PLANNED":
        raise err("ERR_FLIGHT_NOT_PLANNED")
    if g.user_id == flight["filed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES")

    drone = db.drones[flight["drone_id"]]
    if drone["status"] == "GROUNDED":
        raise err("ERR_DRONE_GROUNDED")
    if calc.blocking_risk_score(drone) >= calc.RISK_BLOCK_THRESHOLD:
        raise err("ERR_DRONE_RISK_TOO_HIGH")

    auth = flight_service.authorization_of(flight)
    if auth is None or auth["status"] != "APPROVED":
        raise err("ERR_AUTHORIZATION_NOT_APPROVED")

    flight["clearance_state"] = "CLEARED"
    flight["released_by_user_id"] = g.user_id
    touch(flight)
    return ok(serializers.flight(flight))


# --- launch: the joint gate (PRD 3.6) ------------------------------------


def _geofence_violation(flight, order, nest, now):
    mid_lat = (Decimal(nest["lat"]) + Decimal(order["dropoff_lat"])) / Decimal(2)
    mid_lon = (Decimal(nest["lon"]) + Decimal(order["dropoff_lon"])) / Decimal(2)
    points = [
        (nest["lat"], nest["lon"]),
        (mid_lat, mid_lon),
        (order["dropoff_lat"], order["dropoff_lon"]),
    ]
    for zone in db.geofence_zones.values():
        if zone["service_area_id"] != order["service_area_id"]:
            continue
        if zone["status"] != "ACTIVE":
            continue
        if not (zone["effective_from"] <= now < zone["effective_to"]):
            continue
        for lat, lon in points:
            distance = calc.planar_distance_km(zone["center_lat"], zone["center_lon"], lat, lon)
            if distance <= Decimal(zone["radius_km"]):
                return True
    return False


@bp.post("/flights/<flight_id>/launch")
@require("DispatchOperator")
def launch_flight(flight_id):
    flight = get_or_404("Flight", flight_id)

    if flight["ops_state"] != "PLANNED":
        raise err("ERR_FLIGHT_NOT_PLANNED")
    if flight["clearance_state"] != "CLEARED":
        raise err("ERR_FLIGHT_NOT_CLEARED")

    order = db.orders[flight["order_id"]]
    area = db.service_areas[order["service_area_id"]]
    nest = db.nests[flight["launch_nest_id"]]
    now = db.now()

    if area["status"] != "ACTIVE":
        raise err("ERR_SERVICE_AREA_SUSPENDED")

    observation = calc.latest_observation(order["service_area_id"])
    if observation is not None and not observation["flyable"]:
        raise err("ERR_WEATHER_NO_GO")

    if _geofence_violation(flight, order, nest, now):
        raise err("ERR_GEOFENCE_VIOLATION")

    drone = db.drones[flight["drone_id"]]
    if drone["status"] == "GROUNDED":
        raise err("ERR_DRONE_GROUNDED")

    auth = flight_service.authorization_of(flight)
    if auth is None or auth["status"] != "APPROVED":
        raise err("ERR_AUTHORIZATION_NOT_APPROVED")
    if not (auth["window_start"] <= now < auth["window_end"]):
        raise err("ERR_AUTHORIZATION_WINDOW_EXPIRED")

    battery = db.batteries.get(flight["battery_id"])
    if battery is None or battery["state"] != "READY":
        raise err("ERR_BATTERY_NOT_READY")
    if Decimal(battery["charge_pct"]) < Decimal(flight["required_energy_pct"]):
        raise err("ERR_INSUFFICIENT_BATTERY")

    flight["ops_state"] = "LAUNCHED"
    touch(flight)

    drone["status"] = "IN_FLIGHT"
    touch(drone)

    battery["state"] = "IN_USE"
    touch(battery)

    order["status"] = "IN_TRANSIT"
    touch(order)

    return ok(serializers.flight(flight))


# --- the sortie (PRD 3.7) ------------------------------------------------


@bp.post("/flights/<flight_id>/arrive")
@require("DispatchOperator")
def arrive_flight(flight_id):
    flight = get_or_404("Flight", flight_id)
    if flight["ops_state"] != "LAUNCHED":
        raise err("ERR_FLIGHT_INVALID_STATE")
    flight["ops_state"] = "DROPPING"
    touch(flight)
    return ok(serializers.flight(flight))


@bp.post("/flights/<flight_id>/drop")
@require("DispatchOperator")
def drop_payload(flight_id):
    body = v.body()
    hover_alt_ft = v.as_integer(body, "hover_alt_ft", gt=0, lte=400)
    photo_ref = v.as_string(body, "photo_ref")

    flight = get_or_404("Flight", flight_id)
    if flight["ops_state"] != "DROPPING":
        raise err("ERR_FLIGHT_INVALID_STATE")

    order = db.orders[flight["order_id"]]
    drop = new_record(
        "DeliveryDrop",
        {
            "flight_id": flight["id"],
            "drop_lat": order["dropoff_lat"],
            "drop_lon": order["dropoff_lon"],
            "hover_alt_ft": hover_alt_ft,
            "photo_ref": photo_ref,
            "confirmed_by_user_id": g.user_id,
        },
        versioned=False,
    )

    flight["ops_state"] = "RETURNING"
    touch(flight)

    # The funds settle: held -> billed. Both ledgers derive from the order status.
    order["status"] = "DELIVERED"
    touch(order)

    return ok(serializers.delivery_drop(drop), 201)


@bp.post("/flights/<flight_id>/recover")
@require("DispatchOperator")
def recover(flight_id):
    body = v.body()
    actual_route_km = v.as_number(body, "actual_route_km", gte=0)

    flight = get_or_404("Flight", flight_id)
    if flight["ops_state"] != "RETURNING":
        raise err("ERR_FLIGHT_INVALID_STATE")

    flight_service.recover_flight(flight, actual_route_km)
    return ok(serializers.flight(flight))


@bp.post("/flights/<flight_id>/abort")
@require("DispatchOperator", "FlightDirector")
def abort(flight_id):
    body = v.body()
    actual_route_km = v.as_number(body, "actual_route_km", required=False, default=None, gte=0)

    flight = get_or_404("Flight", flight_id)
    if flight["ops_state"] in ("RECOVERED", "ABORTED"):
        raise err("ERR_FLIGHT_TERMINAL")

    flight_service.abort_flight(flight, "OPERATOR", actual_route_km=actual_route_km)
    return ok(serializers.flight(flight))
