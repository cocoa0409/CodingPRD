"""Broker, Driver, and RateSchedule endpoints."""
from flask import Blueprint

from db import db, new_common, new_immutable_common, touch
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_enum,
                     require_int, require_number, require_string)
from middleware import require_roles
from response import ok_list, ok_object
from serializers import serialize, serialize_list
from services.cascades import broker_suspend_cascade

bp = Blueprint("providers", __name__)

MODALITY = {"AMBULATORY", "WHEELCHAIR", "STRETCHER"}


def get_broker_or_404(broker_id):
    b = db.brokers.get(broker_id)
    if b is None:
        raise err("ERR_NOT_FOUND", "Broker not found")
    return b


def get_driver_or_404(driver_id):
    d = db.drivers.get(driver_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "Driver not found")
    return d


# ---- Broker ----

@bp.route("/brokers", methods=["POST"])
def create_broker():
    require_roles("Coordinator")
    body = get_json_body()
    name = require_string(body, "name")
    covered = body.get("covered_counties")
    if not isinstance(covered, list) or not all(isinstance(c, str) for c in covered):
        raise err("ERR_INVALID_REQUEST", "covered_counties must be an array of county codes")
    max_modality = require_enum(body, "max_modality", MODALITY)
    free_deadhead_miles = require_number(body, "free_deadhead_miles")
    deadhead_rate = require_int(body, "deadhead_rate_cents_per_mile")

    broker = new_common()
    broker.update({
        "name": name,
        "covered_counties": list(covered),
        "max_modality": max_modality,
        "free_deadhead_miles": free_deadhead_miles,
        "deadhead_rate_cents_per_mile": deadhead_rate,
        "status": "ACTIVE",
    })
    db.brokers[broker["id"]] = broker
    return ok_object(serialize(broker), status=201)


@bp.route("/brokers/<broker_id>", methods=["GET"])
def get_broker(broker_id):
    require_roles("Coordinator", "Broker", "Auditor")
    return ok_object(serialize(get_broker_or_404(broker_id)))


@bp.route("/brokers/<broker_id>/suspend", methods=["POST"])
def suspend_broker(broker_id):
    require_roles("Coordinator")
    broker = get_broker_or_404(broker_id)
    if broker["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Broker is not ACTIVE")
    broker["status"] = "SUSPENDED"
    broker_suspend_cascade(broker)
    touch(broker)
    return ok_object(serialize(broker))


@bp.route("/brokers/<broker_id>/reinstate", methods=["POST"])
def reinstate_broker(broker_id):
    require_roles("Coordinator")
    broker = get_broker_or_404(broker_id)
    if broker["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Broker is not SUSPENDED")
    broker["status"] = "ACTIVE"
    touch(broker)
    return ok_object(serialize(broker))


@bp.route("/brokers/<broker_id>/drivers", methods=["GET"])
def list_broker_drivers(broker_id):
    require_roles("Coordinator", "Broker", "Auditor")
    get_broker_or_404(broker_id)
    limit, offset = parse_pagination()
    items = [d for d in db.drivers.values() if d["broker_id"] == broker_id]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


# ---- Driver ----

@bp.route("/drivers", methods=["POST"])
def create_driver():
    require_roles("Broker")
    body = get_json_body()
    if "broker_id" not in body or body["broker_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: broker_id")
    broker_id = body["broker_id"]
    if broker_id not in db.brokers:
        raise err("ERR_FK_NOT_FOUND", "broker_id does not reference an existing Broker")
    full_name = require_string(body, "full_name")
    vehicle_modality = require_enum(body, "vehicle_modality", MODALITY)
    base_county = require_string(body, "base_county")

    driver = new_common()
    driver.update({
        "broker_id": broker_id,
        "full_name": full_name,
        "vehicle_modality": vehicle_modality,
        "base_county": base_county,
        "status": "AVAILABLE",
    })
    db.drivers[driver["id"]] = driver
    return ok_object(serialize(driver), status=201)


@bp.route("/drivers/<driver_id>", methods=["GET"])
def get_driver(driver_id):
    require_roles("Coordinator", "Broker", "Auditor", "Driver")
    return ok_object(serialize(get_driver_or_404(driver_id)))


@bp.route("/drivers/<driver_id>/offline", methods=["POST"])
def driver_offline(driver_id):
    require_roles("Broker")
    driver = get_driver_or_404(driver_id)
    if driver["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Driver is not AVAILABLE")
    driver["status"] = "OFFLINE"
    touch(driver)
    return ok_object(serialize(driver))


@bp.route("/drivers/<driver_id>/online", methods=["POST"])
def driver_online(driver_id):
    require_roles("Broker")
    driver = get_driver_or_404(driver_id)
    if driver["status"] != "OFFLINE":
        raise err("ERR_INVALID_STATE", "Driver is not OFFLINE")
    driver["status"] = "AVAILABLE"
    touch(driver)
    return ok_object(serialize(driver))


# ---- RateSchedule ----

@bp.route("/rate-schedules", methods=["POST"])
def create_rate_schedule():
    require_roles("Coordinator")
    body = get_json_body()
    modality = require_enum(body, "modality", MODALITY)
    base_fare = require_int(body, "base_fare_cents")
    loaded_rate = require_int(body, "loaded_rate_cents_per_mile")
    dwell_free = require_int(body, "dwell_free_minutes")
    dwell_rate = require_int(body, "dwell_cents_per_minute")

    rs = new_immutable_common()
    rs.update({
        "modality": modality,
        "base_fare_cents": base_fare,
        "loaded_rate_cents_per_mile": loaded_rate,
        "dwell_free_minutes": dwell_free,
        "dwell_cents_per_minute": dwell_rate,
    })
    db.rate_schedules[rs["id"]] = rs
    return ok_object(serialize(rs), status=201)


@bp.route("/rate-schedules/<rs_id>", methods=["GET"])
def get_rate_schedule(rs_id):
    require_roles("Coordinator", "Broker", "Auditor")
    rs = db.rate_schedules.get(rs_id)
    if rs is None:
        raise err("ERR_NOT_FOUND", "RateSchedule not found")
    return ok_object(serialize(rs))
