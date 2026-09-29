"""Vehicles, drivers and rider accounts -- the zone's reference data."""
from flask import Blueprint

import db
import listing
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import cascades

bp = Blueprint("fleet", __name__)

VEHICLE_STATUSES = ("AVAILABLE", "IN_MAINTENANCE", "RETIRED")
VEHICLE_TRANSITIONS = {
    ("AVAILABLE", "IN_MAINTENANCE"),
    ("IN_MAINTENANCE", "AVAILABLE"),
    ("AVAILABLE", "RETIRED"),
    ("IN_MAINTENANCE", "RETIRED"),
}
DRIVER_STATUSES = ("ACTIVE", "SUSPENDED")
DRIVER_TRANSITIONS = {("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")}
FARE_CATEGORIES = ("FULL", "REDUCED", "PARATRANSIT")
MOBILITY_DEVICES = ("NONE", "WHEELCHAIR")
LIVE_BLOCK_STATES = ("SCHEDULED", "OPEN")
CONFIGURABLE_ZONE_STATES = ("DRAFT", "ACTIVE")


def _zone(zone_id):
    zone = db.service_zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")
    return zone


def _require_configurable(zone):
    if zone["status"] not in CONFIGURABLE_ZONE_STATES:
        raise ApiError("ERR_ZONE_NOT_ACTIVE")


def get_vehicle(vehicle_id):
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")
    return vehicle


def get_driver(driver_id):
    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    return driver


def get_rider(rider_id):
    rider = db.riders.get(rider_id)
    if rider is None:
        raise ApiError("ERR_RIDER_NOT_FOUND")
    return rider


# --------------------------------------------------------------------------
# vehicles
# --------------------------------------------------------------------------

@bp.post("/vehicles")
@endpoint(["ZoneAdmin"])
def create_vehicle():
    body = validation.get_body()
    zone_raw = validation.raw_fk(body, "zone_id")
    zone = _zone(zone_raw) if zone_raw is not None else None

    zone_id = validation.req_str(body, "zone_id")
    vehicle_code = validation.req_str(body, "vehicle_code")
    seat_capacity = validation.req_int(body, "seat_capacity", 1, 24)
    wav_positions = validation.opt_int(body, "wav_positions", 0, 0, 4)
    if zone is None:
        zone = _zone(zone_id)

    _require_configurable(zone)

    vehicle = db.base_record()
    vehicle.update({
        "zone_id": zone["id"],
        "vehicle_code": vehicle_code,
        "seat_capacity": seat_capacity,
        "wav_positions": wav_positions,
        "is_wav": wav_positions >= 1,
        "status": "AVAILABLE",
    })
    db.vehicles.add(vehicle)
    return response.created(serializers.pick(vehicle, serializers.VEHICLE))


@bp.post("/vehicles/<vehicle_id>/status")
@endpoint(["ZoneAdmin", "Dispatcher"])
def set_vehicle_status(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    body = validation.get_body()
    wanted = validation.req_enum(body, "status", VEHICLE_STATUSES)

    if (vehicle["status"], wanted) not in VEHICLE_TRANSITIONS:
        raise ApiError("ERR_INVALID_VEHICLE_STATE")
    if wanted == "RETIRED":
        for block in db.vehicle_blocks.values():
            if block["vehicle_id"] == vehicle["id"] and \
                    block["state"] in LIVE_BLOCK_STATES:
                raise ApiError("ERR_INVALID_VEHICLE_STATE")

    vehicle["status"] = wanted
    db.touch(vehicle)
    return response.object_response(serializers.pick(vehicle, serializers.VEHICLE))


@bp.get("/vehicles/<vehicle_id>")
@endpoint(ALL_ROLES)
def read_vehicle(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    return response.object_response(serializers.pick(vehicle, serializers.VEHICLE))


@bp.get("/vehicles")
@endpoint(ALL_ROLES)
def list_vehicles():
    return listing.list_endpoint(
        db.vehicles.ordered(), serializers.VEHICLE,
        {"zone_id": "zone_id", "status": "status", "is_wav": ("is_wav", "bool")})


# --------------------------------------------------------------------------
# drivers
# --------------------------------------------------------------------------

@bp.post("/drivers")
@endpoint(["ZoneAdmin"])
def create_driver():
    body = validation.get_body()
    zone_raw = validation.raw_fk(body, "zone_id")
    zone = _zone(zone_raw) if zone_raw is not None else None

    zone_id = validation.req_str(body, "zone_id")
    driver_code = validation.req_str(body, "driver_code")
    wav_certified = validation.opt_bool(body, "wav_certified", False)
    if zone is None:
        zone = _zone(zone_id)

    _require_configurable(zone)

    driver = db.base_record()
    driver.update({
        "zone_id": zone["id"],
        "driver_code": driver_code,
        "wav_certified": wav_certified,
        "status": "ACTIVE",
        "consecutive_decline_count": 0,
    })
    db.drivers.add(driver)
    return response.created(serializers.pick(driver, serializers.DRIVER))


@bp.post("/drivers/<driver_id>/status")
@endpoint(["ZoneAdmin", "Dispatcher"])
def set_driver_status(driver_id):
    driver = get_driver(driver_id)
    body = validation.get_body()
    wanted = validation.req_enum(body, "status", DRIVER_STATUSES)

    if (driver["status"], wanted) not in DRIVER_TRANSITIONS:
        raise ApiError("ERR_INVALID_DRIVER_STATE")

    if wanted == "SUSPENDED":
        cascades.suspend_driver(driver)
    else:
        driver["status"] = "ACTIVE"
        driver["consecutive_decline_count"] = 0
        db.touch(driver)
    return response.object_response(serializers.pick(driver, serializers.DRIVER))


@bp.get("/drivers/<driver_id>")
@endpoint(ALL_ROLES)
def read_driver(driver_id):
    driver = get_driver(driver_id)
    return response.object_response(serializers.pick(driver, serializers.DRIVER))


@bp.get("/drivers")
@endpoint(ALL_ROLES)
def list_drivers():
    return listing.list_endpoint(
        db.drivers.ordered(), serializers.DRIVER,
        {"zone_id": "zone_id", "status": "status",
         "wav_certified": ("wav_certified", "bool")})


# --------------------------------------------------------------------------
# riders
# --------------------------------------------------------------------------

@bp.post("/riders")
@endpoint(["ZoneAdmin"])
def create_rider():
    body = validation.get_body()
    zone_raw = validation.raw_fk(body, "zone_id")
    zone = _zone(zone_raw) if zone_raw is not None else None

    zone_id = validation.req_str(body, "zone_id")
    rider_code = validation.req_str(body, "rider_code")
    fare_category = validation.opt_enum(body, "fare_category", FARE_CATEGORIES,
                                        "FULL")
    mobility_device = validation.opt_enum(body, "mobility_device",
                                          MOBILITY_DEVICES, "NONE")
    if zone is None:
        zone = _zone(zone_id)

    _require_configurable(zone)

    rider = db.base_record()
    rider.update({
        "zone_id": zone["id"],
        "rider_code": rider_code,
        "fare_category": fare_category,
        "mobility_device": mobility_device,
        "fare_counter_date": None,
        "fare_counter_week_start": None,
        "daily_fare_paid_cents": 0,
        "weekly_fare_paid_cents": 0,
    })
    db.riders.add(rider)
    return response.created(serializers.pick(rider, serializers.RIDER))


@bp.get("/riders/<rider_id>")
@endpoint(ALL_ROLES)
def read_rider(rider_id):
    rider = get_rider(rider_id)
    return response.object_response(serializers.pick(rider, serializers.RIDER))


@bp.get("/riders")
@endpoint(ALL_ROLES)
def list_riders():
    return listing.list_endpoint(
        db.riders.ordered(), serializers.RIDER,
        {"zone_id": "zone_id", "fare_category": "fare_category",
         "mobility_device": "mobility_device"})
