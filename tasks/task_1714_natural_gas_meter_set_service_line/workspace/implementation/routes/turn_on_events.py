"""TurnOnEvent endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_STATE,
    ERR_LOAD_APP_MISMATCH,
    ERR_METER_NOT_READY,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    require_bool,
    require_fields,
    require_number,
    require_roles,
)
from response import success_list, success_object
from services.calculations import turn_on_verified
from services.domain import get_application, get_load, get_turn_on, touch

bp = Blueprint("turn_on_events", __name__)


@bp.route("/turn-on-events", methods=["POST"])
def create_turn_on():
    user_id, _ = require_roles("MeterTechnician")
    body = get_body()
    require_fields(body, "service_application_id", "appliance_load_id")
    app = get_application(body["service_application_id"])
    load = get_load(body["appliance_load_id"])
    check_app_mutable(app)
    if load["service_application_id"] != app["id"]:
        raise_error(ERR_LOAD_APP_MISMATCH, "The appliance load belongs to a different application")
    now = db.now_iso()
    event = {
        "id": new_id(),
        "service_application_id": app["id"],
        "appliance_load_id": load["id"],
        "technician_user_id": user_id,
        "co_reading_ppm": None,
        "odor_detected": None,
        "ignition_verified": None,
        "venting_verified": None,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.turn_on_events[event["id"]] = event
    return success_object(event, 201)


@bp.route("/turn-on-events/<tid>", methods=["GET"])
def get_one_turn_on(tid):
    require_roles(*ANY_ROLE)
    return success_object(get_turn_on(tid))


@bp.route("/turn-on-events", methods=["GET"])
def list_turn_ons():
    require_roles(*ANY_ROLE)
    records = list(db.turn_on_events.values())
    app_id = request.args.get("service_application_id")
    load_id = request.args.get("appliance_load_id")
    status = request.args.get("status")
    if app_id is not None:
        records = [t for t in records if t["service_application_id"] == app_id]
    if load_id is not None:
        records = [t for t in records if t["appliance_load_id"] == load_id]
    if status is not None:
        records = [t for t in records if t["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


@bp.route("/turn-on-events/<tid>/complete", methods=["POST"])
def complete_turn_on(tid):
    require_roles("MeterTechnician")
    event = get_turn_on(tid)
    app = get_application(event["service_application_id"])
    body = get_body()
    require_fields(body, "co_reading_ppm", "odor_detected", "ignition_verified", "venting_verified")
    co_reading = require_number(body, "co_reading_ppm")
    odor = require_bool(body, "odor_detected")
    ignition = require_bool(body, "ignition_verified")
    venting = require_bool(body, "venting_verified")
    check_app_mutable(app)
    if event["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Only SCHEDULED turn-on events can be completed")
    if app["status"] != "TURN_ON":
        raise_error(ERR_METER_NOT_READY, "Application is not in TURN_ON")
    event["co_reading_ppm"] = co_reading
    event["odor_detected"] = odor
    event["ignition_verified"] = ignition
    event["venting_verified"] = venting
    event["status"] = "VERIFIED" if turn_on_verified(co_reading, odor, ignition, venting) else "FAILED"
    touch(event)
    return success_object(event)


@bp.route("/turn-on-events/<tid>/retry", methods=["POST"])
def retry_turn_on(tid):
    require_roles("MeterTechnician")
    event = get_turn_on(tid)
    app = get_application(event["service_application_id"])
    check_app_mutable(app)
    if event["status"] != "FAILED":
        raise_error(ERR_INVALID_STATE, "Only FAILED turn-on events can be retried")
    event["status"] = "SCHEDULED"
    touch(event)
    return success_object(event)
