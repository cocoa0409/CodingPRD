"""Devices and meter readings (PRD §3.2)."""
from flask import Blueprint, request

from errors import err
from common import (require, ALL_ROLES, get_body, ok_object, list_response,
                    require_str, require_number, require_enum, opt_number)
from models import get_or_404, insert, touch
from store import db, parse_iso

bp_devices = Blueprint("devices", __name__)

DEVICE_TYPES = {"BATTERY", "THERMOSTAT", "EV_CHARGER"}
READING_TYPES = {"BASELINE_WINDOW", "EVENT_WINDOW"}


def _require_iso(body, field):
    require_str(body, field)
    try:
        parse_iso(body[field])
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field %s must be an ISO 8601 datetime." % field)
    return body[field]


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
@bp_devices.route("/dr/devices", methods=["POST"])
def create_device():
    uid, _ = require(["Aggregator"])
    body = get_body()
    # step 4: FK existence (customer_id)
    if body.get("customer_id") is not None:
        get_or_404("customers", body["customer_id"])
    # step 6: required + typed
    customer_id = require_str(body, "customer_id")
    nameplate = require_number(body, "nameplate_kw", gt=0)
    capacity = opt_number(body, "capacity_kwh")
    # step 7: enum
    device_type = require_enum(body, "device_type", DEVICE_TYPES)
    rec = insert("devices", {
        "customer_id": customer_id,
        "aggregator_id": uid,  # bound to acting aggregator
        "device_type": device_type,
        "nameplate_kw": nameplate,
        "capacity_kwh": capacity,
        "status": "ACTIVE",
    })
    return ok_object(rec, status=201)


@bp_devices.route("/dr/devices/<did>", methods=["GET"])
def get_device(did):
    require(ALL_ROLES)
    return ok_object(get_or_404("devices", did))


@bp_devices.route("/dr/devices", methods=["GET"])
def list_devices():
    require(ALL_ROLES)
    customer_id = request.args.get("customer_id")
    aggregator_id = request.args.get("aggregator_id")
    status = request.args.get("status")
    records = []
    for d in db.data["devices"].values():
        if customer_id is not None and d["customer_id"] != customer_id:
            continue
        if aggregator_id is not None and d["aggregator_id"] != aggregator_id:
            continue
        if status is not None and d["status"] != status:
            continue
        records.append(d)
    return list_response(records)


@bp_devices.route("/dr/devices/<did>/decommission", methods=["POST"])
def decommission_device(did):
    uid, _ = require(["Aggregator"])
    device = get_or_404("devices", did)
    if device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own this device.")
    if device["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Device is not ACTIVE.")
    for e in db.data["enrollments"].values():
        if e["device_id"] == did and e["status"] == "ACTIVE":
            raise err("ERR_INVALID_STATE", "Device has an ACTIVE enrollment.")
    device["status"] = "DECOMMISSIONED"
    touch(device)
    return ok_object(device)


# ---------------------------------------------------------------------------
# Meter readings
# ---------------------------------------------------------------------------
@bp_devices.route("/dr/devices/<did>/meter-readings", methods=["POST"])
def create_meter_reading(did):
    uid, _ = require(["Aggregator"])
    device = get_or_404("devices", did)          # step 3 path
    body = get_body()
    # step 4: FK existence for dispatch_event_id when supplied
    dispatch_event_id = body.get("dispatch_event_id")
    if dispatch_event_id is not None:
        get_or_404("dispatch_events", dispatch_event_id)
    # step 5: ownership
    if device["aggregator_id"] != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Aggregator does not own this device.")
    # step 6: required + typed
    interval_start = _require_iso(body, "interval_start")
    interval_end = _require_iso(body, "interval_end")
    kw_load = require_number(body, "kw_load", ge=0)
    # step 7: enum
    reading_type = require_enum(body, "reading_type", READING_TYPES)
    # business: interval well-formed (PRD §3.2 order: well-formed before overlap)
    start_dt = parse_iso(interval_start)
    end_dt = parse_iso(interval_end)
    if not start_dt < end_dt:
        raise err("ERR_VALIDATION", "interval_start must be before interval_end.")
    # business: no overlap with same device + reading_type
    for r in db.data["meter_readings"].values():
        if r["device_id"] != did or r["reading_type"] != reading_type:
            continue
        es = parse_iso(r["interval_start"])
        ee = parse_iso(r["interval_end"])
        if start_dt < ee and es < end_dt:  # adjacency (end==start) allowed
            raise err("ERR_READING_INTERVAL_OVERLAP",
                      "Reading interval overlaps an existing reading.")
    rec = insert("meter_readings", {
        "device_id": did,
        "dispatch_event_id": dispatch_event_id,
        "interval_start": interval_start,
        "interval_end": interval_end,
        "kw_load": kw_load,
        "reading_type": reading_type,
    }, common=False)
    return ok_object(rec, status=201)


@bp_devices.route("/dr/devices/<did>/meter-readings", methods=["GET"])
def list_device_readings(did):
    require(ALL_ROLES)
    get_or_404("devices", did)
    reading_type = request.args.get("reading_type")
    records = [r for r in db.data["meter_readings"].values()
               if r["device_id"] == did
               and (reading_type is None or r["reading_type"] == reading_type)]
    return list_response(records)


@bp_devices.route("/dr/meter-readings/<rid>", methods=["GET"])
def get_meter_reading(rid):
    require(ALL_ROLES)
    return ok_object(get_or_404("meter_readings", rid))


@bp_devices.route("/dr/meter-readings", methods=["GET"])
def list_meter_readings():
    require(ALL_ROLES)
    device_id = request.args.get("device_id")
    dispatch_event_id = request.args.get("dispatch_event_id")
    reading_type = request.args.get("reading_type")
    records = []
    for r in db.data["meter_readings"].values():
        if device_id is not None and r["device_id"] != device_id:
            continue
        if dispatch_event_id is not None and r.get("dispatch_event_id") != dispatch_event_id:
            continue
        if reading_type is not None and r["reading_type"] != reading_type:
            continue
        records.append(r)
    return list_response(records)
