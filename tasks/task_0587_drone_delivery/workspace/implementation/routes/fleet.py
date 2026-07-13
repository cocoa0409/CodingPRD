"""Airframes, packs and customers (PRD 3.2, 3.3)."""
from decimal import Decimal

from flask import Blueprint

import serializers
import validation as v
from auth import require
from db import db, get_or_404, new_record, touch
from errors import err
from response import ok
from routes import filtered, list_response

bp = Blueprint("fleet", __name__)

STAFF = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "MaintenanceTech")
CUSTOMER_READERS = ("PlatformAdmin", "DispatchOperator", "FlightDirector", "Customer")
DRONE_STATUSES = ("IDLE", "RESERVED", "IN_FLIGHT", "GROUNDED")
BATTERY_STATES = ("CHARGING", "READY", "IN_USE", "COOLDOWN", "RETIRED")


# --- drones ---------------------------------------------------------------


@bp.post("/drones")
@require("PlatformAdmin")
def create_drone():
    body = v.body()
    home_nest_id = v.as_string(body, "home_nest_id")
    tail_number = v.as_string(body, "tail_number")
    airframe_class = v.as_enum(body, "airframe_class", ("LIGHT", "HEAVY"))
    max_payload_g = v.as_integer(body, "max_payload_g", gt=0)
    cruise_speed_kmh = v.as_number(body, "cruise_speed_kmh", gt=0)
    hours_since_service = v.as_number(
        body, "hours_since_service", required=False, default=Decimal("0"), gte=0
    )

    get_or_404("Nest", home_nest_id)
    if any(d["tail_number"] == tail_number for d in db.drones.values()):
        raise err("ERR_DUPLICATE_TAIL_NUMBER")

    rec = new_record(
        "Drone",
        {
            "home_nest_id": home_nest_id,
            "tail_number": tail_number,
            "airframe_class": airframe_class,
            "max_payload_g": max_payload_g,
            "cruise_speed_kmh": cruise_speed_kmh,
            "hours_since_service": hours_since_service,
            "flight_hours": Decimal("0"),
            "status": "IDLE",
            "installed_battery_id": None,
        },
    )
    return ok(serializers.drone(rec), 201)


@bp.get("/drones")
@require(*STAFF)
def list_drones():
    limit, offset = v.pagination()
    rows = filtered(
        db.drones.values(),
        home_nest_id=v.query_str("home_nest_id"),
        installed_battery_id=v.query_str("installed_battery_id"),
        status=v.query_enum("status", DRONE_STATUSES),
    )
    return list_response(rows, serializers.drone, limit, offset)


@bp.get("/drones/<drone_id>")
@require(*STAFF)
def read_drone(drone_id):
    return ok(serializers.drone(get_or_404("Drone", drone_id)))


@bp.post("/drones/<drone_id>/install-battery")
@require("MaintenanceTech", "PlatformAdmin")
def install_battery(drone_id):
    body = v.body()
    battery_id = v.as_string(body, "battery_id")

    drone = get_or_404("Drone", drone_id)
    battery = get_or_404("Battery", battery_id)

    if drone["status"] not in ("IDLE", "GROUNDED"):
        raise err("ERR_BATTERY_NOT_READY", "The airframe must be IDLE or GROUNDED.")
    if battery["nest_id"] != drone["home_nest_id"]:
        raise err("ERR_BATTERY_NOT_READY", "The pack is not stored at the airframe's home nest.")
    if battery["state"] in ("IN_USE", "RETIRED"):
        raise err("ERR_BATTERY_NOT_READY", "The pack is %s." % battery["state"])

    drone["installed_battery_id"] = battery_id
    touch(drone)
    return ok(serializers.drone(drone))


# --- batteries ------------------------------------------------------------


@bp.post("/batteries")
@require("PlatformAdmin", "MaintenanceTech")
def create_battery():
    body = v.body()
    nest_id = v.as_string(body, "nest_id")
    serial = v.as_string(body, "serial")
    charge_pct = v.as_number(body, "charge_pct", required=False, default=Decimal("100"), gte=0, lte=100)
    cycle_count = v.as_integer(body, "cycle_count", required=False, default=0, gte=0)

    get_or_404("Nest", nest_id)
    rec = new_record(
        "Battery",
        {
            "nest_id": nest_id,
            "serial": serial,
            "charge_pct": charge_pct,
            "cycle_count": cycle_count,
            "state": "CHARGING",
        },
    )
    return ok(serializers.battery(rec), 201)


@bp.get("/batteries")
@require(*STAFF)
def list_batteries():
    limit, offset = v.pagination()
    rows = filtered(
        db.batteries.values(),
        nest_id=v.query_str("nest_id"),
        state=v.query_enum("state", BATTERY_STATES),
    )
    return list_response(rows, serializers.battery, limit, offset)


@bp.get("/batteries/<battery_id>")
@require(*STAFF)
def read_battery(battery_id):
    return ok(serializers.battery(get_or_404("Battery", battery_id)))


@bp.post("/batteries/<battery_id>/charge")
@require("MaintenanceTech", "PlatformAdmin")
def charge_battery(battery_id):
    body = v.body()
    target = v.as_number(body, "target_charge_pct", gte=0, lte=100)

    battery = get_or_404("Battery", battery_id)
    if battery["state"] not in ("CHARGING", "COOLDOWN", "READY"):
        raise err("ERR_BATTERY_NOT_READY", "A %s pack cannot be charged." % battery["state"])

    battery["charge_pct"] = target
    battery["state"] = "READY"
    touch(battery)
    return ok(serializers.battery(battery))


# --- customers ------------------------------------------------------------


@bp.post("/customers")
@require("PlatformAdmin")
def create_customer():
    body = v.body()
    rec = new_record(
        "Customer",
        {
            "name": v.as_string(body, "name"),
            "email": v.as_string(body, "email"),
            "dropoff_lat": v.as_number(body, "dropoff_lat"),
            "dropoff_lon": v.as_number(body, "dropoff_lon"),
        },
    )
    return ok(serializers.customer(rec), 201)


@bp.get("/customers/<customer_id>")
@require(*CUSTOMER_READERS)
def read_customer(customer_id):
    return ok(serializers.customer(get_or_404("Customer", customer_id)))
