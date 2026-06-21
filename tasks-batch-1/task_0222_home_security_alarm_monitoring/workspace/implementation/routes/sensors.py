"""Sensor endpoints: enroll, read, list, bypass/restore/remove."""
from flask import Blueprint, request

from db import db, new_id, new_common, touch
from errors import (
    err,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_ACCOUNT_OWNER,
    ERR_SENSOR_LIMIT_EXCEEDED,
    ERR_DUPLICATE_ZONE,
)
from middleware import authenticate, require_role
from response import success, list_response
from services import validate, common
from services.derive import serialize_sensor, system_sensor_count

bp = Blueprint("sensors", __name__)

SENSOR_TYPES = {"DOOR", "MOTION", "GLASS_BREAK", "SMOKE", "CO", "PANIC"}


def _ownership_check(caller, sensor):
    if caller.role != "Subscriber":
        return
    system = db.systems.get(sensor["system_id"])
    owner_account = system["account_id"] if system else None
    if caller.user_id != owner_account:
        raise err(ERR_NOT_ACCOUNT_OWNER, "Subscriber is not the owner of this sensor's account")


@bp.route("/sensors", methods=["POST"])
def create_sensor():
    caller = authenticate()
    require_role(caller, {"Administrator"})
    body = validate.get_body()

    # FK presence + resolution
    system_id = validate.require_str(body, "system_id")
    if system_id not in db.systems:
        raise err(ERR_REFERENCE_NOT_FOUND, "system_id does not resolve: %s" % system_id)

    zone_number = validate.require_int(body, "zone_number", minimum=1)
    sensor_type = validate.require_enum(body, "sensor_type", SENSOR_TYPES)

    system = db.systems[system_id]
    account = db.accounts.get(system["account_id"])
    plan = db.monitoring_plans.get(account["plan_id"]) if account else None

    # Sensor limit (priority 10) before duplicate zone (priority 11)
    current = system_sensor_count(system_id)
    if plan is not None and current + 1 > plan["max_sensors"]:
        raise err(ERR_SENSOR_LIMIT_EXCEEDED, "Enrolling would exceed plan.max_sensors")

    # Duplicate zone among non-REMOVED sensors on the same system (priority 11)
    for s in db.sensors.values():
        if (
            s["system_id"] == system_id
            and s["status"] != "REMOVED"
            and s["zone_number"] == zone_number
        ):
            raise err(ERR_DUPLICATE_ZONE, "zone_number already in use on this system")

    sid = new_id()
    sensor = {"id": sid}
    sensor.update(new_common())
    sensor.update({
        "system_id": system_id,
        "zone_number": zone_number,
        "sensor_type": sensor_type,
        "status": "ENROLLED",
    })
    db.sensors[sid] = sensor
    return success(serialize_sensor(sensor), http_status=201)


@bp.route("/sensors/<sid>", methods=["GET"])
def get_sensor(sid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    sensor = common.lookup(db.sensors, sid)
    return success(serialize_sensor(sensor))


@bp.route("/sensors", methods=["GET"])
def list_sensors():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    system_id = request.args.get("system_id")
    status = request.args.get("status")
    items = list(db.sensors.values())
    if system_id is not None:
        items = [s for s in items if s["system_id"] == system_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_sensor(s) for s in window], limit, offset, total)


@bp.route("/sensors/<sid>/bypass", methods=["POST"])
def bypass_sensor(sid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "Administrator"})
    sensor = common.lookup(db.sensors, sid)
    _ownership_check(caller, sensor)
    if sensor["status"] != "ENROLLED":
        raise err(ERR_INVALID_STATE, "Sensor is not ENROLLED")
    sensor["status"] = "BYPASSED"
    touch(sensor)
    return success(serialize_sensor(sensor))


@bp.route("/sensors/<sid>/restore", methods=["POST"])
def restore_sensor(sid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "Administrator"})
    sensor = common.lookup(db.sensors, sid)
    _ownership_check(caller, sensor)
    if sensor["status"] != "BYPASSED":
        raise err(ERR_INVALID_STATE, "Sensor is not BYPASSED")
    sensor["status"] = "ENROLLED"
    touch(sensor)
    return success(serialize_sensor(sensor))


@bp.route("/sensors/<sid>/remove", methods=["POST"])
def remove_sensor(sid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    sensor = common.lookup(db.sensors, sid)
    if sensor["status"] not in ("ENROLLED", "BYPASSED"):
        raise err(ERR_INVALID_STATE, "Sensor is not removable")
    sensor["status"] = "REMOVED"
    touch(sensor)
    # sensor_count is derived (non-REMOVED count), so it decrements automatically.
    return success(serialize_sensor(sensor))
