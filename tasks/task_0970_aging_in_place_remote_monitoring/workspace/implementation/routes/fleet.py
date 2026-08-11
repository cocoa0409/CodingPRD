"""Sensor kits, devices, telemetry ingest, sensor events."""
from flask import Blueprint, request

import db
import errors
from middleware import (require_roles, get_body, req_str, opt_int, opt_str,
                        req_enum, req_dt, query_enum, check_senior_scope,
                        scoped_list, EVENT_TYPES, DEVICE_STATUSES)
from response import ok, list_ok
from services import (create_record, touch, ser, posture, current_subscription,
                      ingest_event, auto_resolve_alert, OPEN_ALERT_STATUSES)

bp = Blueprint("fleet", __name__)


# ------------------------------------------------------------------ kits ---

@bp.post("/v1/sensor-kits")
def create_kit():
    require_roles(["PlatformAdmin"])
    b = get_body()
    senior_id = req_str(b, "senior_id")
    if senior_id not in db.seniors:
        raise errors.not_found("Senior not found")
    count = opt_int(b, "motion_sensor_count", None, lo=0)
    if count is None:
        sub = current_subscription(senior_id)
        plan = db.plans.get(sub["plan_id"]) if sub else None
        if plan is None:
            raise errors.not_found("No subscription plan found to default motion_sensor_count")
        count = plan["included_motion_sensors"]
    kit = create_record(db.kits, {
        "senior_id": senior_id,
        "motion_sensor_count": count,
        "status": "ORDERED",
    })
    kseq = db.next_kit_seq()
    specs = [("GATEWAY", 1), ("WEARABLE", 1)] + [("MOTION", i + 1) for i in range(count)]
    for dtype, idx in specs:
        create_record(db.devices, {
            "kit_id": kit["id"],
            "senior_id": senior_id,
            "device_type": dtype,
            "serial": f"{kseq}-{dtype}-{idx}",
            "status": "PROVISIONED",
            "battery_percent": 100,
            "last_seen_at": None,
        })
    return ok(ser(kit), 201)


def _get_kit(kit_id):
    k = db.kits.get(kit_id)
    if k is None:
        raise errors.not_found("Sensor kit not found")
    return k


@bp.get("/v1/sensor-kits/<kit_id>")
def get_kit(kit_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Installer"])
    k = _get_kit(kit_id)
    if role == "Installer":
        if not any(a for a in db.appointments.values()
                   if a["kit_id"] == kit_id and a["installer_id"] == uid):
            raise errors.ownership()
    return ok(ser(k))


@bp.get("/v1/sensor-kits")
def list_kits():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    recs = list(db.kits.values())
    sid = request.args.get("senior_id")
    if sid is not None:
        recs = [r for r in recs if r["senior_id"] == sid]
    return list_ok(recs, ser)


@bp.post("/v1/sensor-kits/<kit_id>/ship")
def ship_kit(kit_id):
    require_roles(["PlatformAdmin"])
    k = _get_kit(kit_id)
    if k["status"] != "ORDERED":
        raise errors.invalid_state("Kit is not ORDERED")
    k["status"] = "SHIPPED"
    touch(k)
    return ok(ser(k))


@bp.post("/v1/sensor-kits/<kit_id>/mark-delivered")
def deliver_kit(kit_id):
    require_roles(["PlatformAdmin"])
    k = _get_kit(kit_id)
    if k["status"] != "SHIPPED":
        raise errors.invalid_state("Kit is not SHIPPED")
    k["status"] = "DELIVERED"
    touch(k)
    return ok(ser(k))


# --------------------------------------------------------------- devices ---

def _get_device(device_id):
    d = db.devices.get(device_id)
    if d is None:
        raise errors.not_found("Device not found")
    return d


@bp.get("/v1/devices/<device_id>")
def get_device(device_id):
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    d = _get_device(device_id)
    check_senior_scope(role, uid, d["senior_id"])
    return ok(ser(d))


@bp.get("/v1/devices")
def list_devices():
    role, uid = require_roles(["PlatformAdmin", "MonitoringAgent", "Caregiver"])
    recs = list(db.devices.values())
    recs = scoped_list(role, uid, recs, request.args.get("senior_id"))
    kid = request.args.get("kit_id")
    if kid is not None:
        recs = [r for r in recs if r["kit_id"] == kid]
    st = query_enum("status", DEVICE_STATUSES)
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_ok(recs, ser)


@bp.post("/v1/devices/<device_id>/decommission")
def decommission_device(device_id):
    require_roles(["PlatformAdmin"])
    d = _get_device(device_id)
    if d["status"] not in ("INSTALLED", "ONLINE", "OFFLINE"):
        raise errors.invalid_state("Device cannot be decommissioned from its current state")
    if d["device_type"] == "GATEWAY" and posture(d["senior_id"]) == "ACTIVE":
        other_functional = any(
            o for o in db.devices.values()
            if o["id"] != d["id"] and o["senior_id"] == d["senior_id"]
            and o["device_type"] == "GATEWAY" and o["status"] in ("ONLINE", "INSTALLED"))
        if not other_functional:
            raise errors.device_safety_required()
    d["status"] = "DECOMMISSIONED"
    touch(d)
    for a in list(db.alerts.values()):
        if (a.get("device_id") == d["id"] and a["alert_type"] in ("LOW_BATTERY", "DEVICE_OFFLINE")
                and a["status"] in OPEN_ALERT_STATUSES):
            auto_resolve_alert(a)
    return ok(ser(d))


# ------------------------------------------------------------- telemetry ---

@bp.post("/v1/telemetry")
def ingest():
    require_roles(["DeviceHub"])
    b = get_body()
    device_id = req_str(b, "device_id")
    event_type = req_enum(b, "event_type", EVENT_TYPES)
    observed_at = req_dt(b, "observed_at")
    battery = opt_int(b, "battery_percent", None, lo=0, hi=100)
    note = opt_str(b, "note")
    device = db.devices.get(device_id)
    if device is None:
        raise errors.not_found("Device not found")
    if observed_at > db.clock:
        raise errors.invalid_request("observed_at must not be later than the current clock")
    ev = ingest_event(device, event_type, observed_at, battery, note)
    return ok(ser(ev), 201)


@bp.get("/v1/sensor-events/<event_id>")
def get_event(event_id):
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    ev = db.events.get(event_id)
    if ev is None:
        raise errors.not_found("Sensor event not found")
    return ok(ser(ev))


@bp.get("/v1/sensor-events")
def list_events():
    require_roles(["PlatformAdmin", "MonitoringAgent"])
    recs = list(db.events.values())
    did = request.args.get("device_id")
    if did is not None:
        recs = [r for r in recs if r["device_id"] == did]
    sid = request.args.get("senior_id")
    if sid is not None:
        recs = [r for r in recs if r["senior_id"] == sid]
    et = query_enum("event_type", EVENT_TYPES)
    if et is not None:
        recs = [r for r in recs if r["event_type"] == et]
    return list_ok(recs, ser)
