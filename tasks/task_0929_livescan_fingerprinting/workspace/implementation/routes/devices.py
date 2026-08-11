from flask import Blueprint, request

import cascades
import constants as C
import derive
import serializers
import validation as V
from envelope import object_response, paginate
from lookups import body_row, path_row, require_record_state, unique_or_400
from store import db
from timeutil import add_days

bp = Blueprint("devices", __name__)


@bp.post("/livescan/devices")
def create_device():
    data = V.body()
    home_site = None
    if data.get("home_site_id") is not None:
        home_site = body_row("sites", data.get("home_site_id"))

    serial_number = V.req_string(data, "serial_number")
    calibrated_at = V.req_instant(data, "calibrated_at")
    if home_site is None:
        V.bad_request("home_site_id is required")
    unique_or_400("devices", "serial_number", serial_number)

    row = db.create(
        "devices",
        {
            "serial_number": serial_number,
            "home_site_id": home_site["id"],
            "last_calibrated_at": calibrated_at,
            "calibration_expires_at": add_days(calibrated_at, C.DEVICE_CALIBRATION_VALID_DAYS),
            "calibration_status": "CALIBRATED",
            "capture_count": 0,
            "tainted_card_count": 0,
        },
    )
    return object_response(serializers.device(row), 201)


@bp.get("/livescan/devices/<id>")
def read_device(id):
    return object_response(serializers.device(path_row("devices", id)))


@bp.get("/livescan/devices")
def list_devices():
    rows = list(db.devices.values())
    home_site_id = request.args.get("home_site_id")
    calibration_status = request.args.get("calibration_status")
    if home_site_id is not None:
        rows = [r for r in rows if r["home_site_id"] == home_site_id]
    if calibration_status is not None:
        rows = [r for r in rows if derive.device_status(r) == calibration_status]
    return paginate(rows, serializers.device)


@bp.post("/livescan/devices/<id>/calibration")
def record_calibration(id):
    device = path_row("devices", id)
    data = V.body()
    calibrated_at = V.req_instant(data, "calibrated_at")

    current = derive.device_status(device)
    require_record_state(current in ("EXPIRED", "QUARANTINED"), "device is %s" % current)

    # Friction point 2(a): the ordering condition is declared on the
    # QUARANTINED -> CALIBRATED leg and is not restated on the EXPIRED leg, so it
    # is enforced only when the device is coming out of quarantine.
    if current == "QUARANTINED" and calibrated_at < device["last_calibrated_at"]:
        V.bad_request("calibrated_at may not be earlier than last_calibrated_at")

    device["last_calibrated_at"] = calibrated_at
    device["calibration_expires_at"] = add_days(calibrated_at, C.DEVICE_CALIBRATION_VALID_DAYS)
    device["calibration_status"] = "CALIBRATED"
    db.touch(device)
    return object_response(serializers.device(device))


@bp.post("/livescan/devices/<id>/calibration-audit")
def calibration_audit(id):
    device = path_row("devices", id)
    data = V.body()
    corrected = V.req_instant(data, "corrected_last_calibrated_at")

    current = derive.device_status(device)
    require_record_state(current in ("CALIBRATED", "EXPIRED"), "device is %s" % current)

    if corrected > device["last_calibrated_at"]:
        V.bad_request("an audit may only move the calibration instant backwards")
    if db.now() <= add_days(corrected, C.DEVICE_CALIBRATION_VALID_DAYS):
        V.bad_request("the corrected certificate has not yet lapsed")

    cascades.run_calibration_audit(device, corrected)
    return object_response(serializers.device(device))
