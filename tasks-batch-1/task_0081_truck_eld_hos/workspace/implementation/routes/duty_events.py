"""DutyStatusEvent endpoints: append/correct, list, fetch, mark-error
(PRD §3.3, §3.4, §3.6)."""
from flask import Blueprint, request

import db
import errors
import model
import response
import serializers as ser
import timeutil
import validation as val
from middleware import get_auth, require_role
from paginate import paginate
from services import hos

bp = Blueprint("duty_events", __name__)

DUTY_STATUSES = {"OFF_DUTY", "SLEEPER_BERTH", "DRIVING", "ON_DUTY_NOT_DRIVING"}
SPECIAL_CATEGORIES = {"NONE", "PERSONAL_CONVEYANCE", "YARD_MOVE"}
RECORD_STATUSES = {"ACTIVE", "INACTIVE_CHANGED", "INACTIVE_ERROR"}


def _latest_active_event(driver_id):
    evs = [e for e in db.duty_events.values()
           if e["driver_id"] == driver_id and e["record_status"] == "ACTIVE"]
    if not evs:
        return None
    evs.sort(key=lambda e: (e["_event_dt"], e["_seq"]))
    return evs[-1]


@bp.route("/eld/duty-events", methods=["POST"])
def append_event():
    user_id, role = get_auth()
    require_role(role, {"Driver"})
    body = val.get_body()

    # --- required field structural read ---
    driver_id = val.require_str(body, "driver_id")
    device_id = val.require_str(body, "device_id")
    duty_status = val.require_present(body, "duty_status")
    val.enum_in(duty_status, DUTY_STATUSES, "duty_status")
    event_time_raw = val.require_str(body, "event_time")
    event_dt = timeutil.parse_iso(event_time_raw)
    if event_dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "event_time is not a valid ISO 8601 instant.")

    special = body.get("special_driving_category", "NONE")
    if special is None:
        special = "NONE"
    val.enum_in(special, SPECIAL_CATEGORIES, "special_driving_category")

    edited_from = body.get("edited_from_event_id")
    if edited_from is not None and not isinstance(edited_from, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "edited_from_event_id must be a string.")
    annotation = val.optional_str(body, "annotation")

    if "expected_driver_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_driver_version is required.")
    expected_version = body["expected_driver_version"]

    # --- priority 4: body FK existence ---
    driver = db.drivers.get(driver_id)
    if driver is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "driver_id not found.")
    device = db.devices.get(device_id)
    if device is None:
        raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "device_id not found.")
    if edited_from is not None:
        if edited_from not in db.duty_events:
            raise errors.err(errors.ERR_REFERENCE_NOT_FOUND, "edited_from_event_id not found.")

    # --- priority 5: ownership (entity-backed Driver) ---
    if user_id != driver_id:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Driver may only append to their own log.")

    # --- driver must exist and be ACTIVE ---
    if driver["status"] != "ACTIVE":
        raise errors.err(errors.ERR_UNAUTHORIZED, "Driver is not ACTIVE.")

    # --- priority 7: device BOUND to driver_id ---
    if device["status"] != "BOUND" or device["bound_driver_id"] != driver_id:
        raise errors.err(errors.ERR_DEVICE_NOT_BOUND, "Device is not bound to driver.")

    # --- priority 8: event order (strictly greater than latest ACTIVE event_time) ---
    latest = _latest_active_event(driver_id)
    if latest is not None and event_dt <= latest["_event_dt"]:
        raise errors.err(errors.ERR_EVENT_OUT_OF_ORDER,
                         "event_time must be strictly greater than the latest event.")

    # --- priority 9: PC authorization ---
    if special == "PERSONAL_CONVEYANCE":
        if not driver["pc_authorized"] or duty_status not in ("DRIVING", "OFF_DUTY"):
            raise errors.err(errors.ERR_PC_NOT_AUTHORIZED,
                             "Personal Conveyance not authorized for this driver/status.")

    # --- priority 10: annotation required ---
    if special != "NONE" or edited_from is not None:
        if annotation is None or annotation == "":
            raise errors.err(errors.ERR_ANNOTATION_REQUIRED, "annotation is required.")

    # --- priority 11: edit target valid (ACTIVE event of same driver) ---
    target = None
    if edited_from is not None:
        target = db.duty_events.get(edited_from)
        if target["record_status"] != "ACTIVE" or target["driver_id"] != driver_id:
            raise errors.err(errors.ERR_EDIT_TARGET_INVALID,
                             "edited_from_event_id is not an ACTIVE event of this driver.")

    # --- priority 18: OCC ---
    if expected_version != driver["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Driver version mismatch.")

    # --- commit ---
    vehicle_id = device["vehicle_id"]
    rec = {
        "driver_id": driver_id,
        "device_id": device_id,
        "vehicle_id": vehicle_id,
        "duty_status": duty_status,
        "special_driving_category": special,
        "event_time": timeutil.iso_now_str(event_dt),
        "duration_minutes": None,
        "record_status": "ACTIVE",
        "compliance_disposition": "COMPLIANT",
        "edited_from_event_id": edited_from,
        "annotation": annotation,
        "_event_dt": event_dt,
    }
    model.stamp_new(rec)
    db.duty_events[rec["id"]] = rec

    # correction: supersede the target
    if target is not None:
        target["record_status"] = "INACTIVE_CHANGED"
        model.touch(target)

    hos.recompute_driver(driver, dismiss_note=hos.NOTE_CORRECTED)
    return response.object_response(ser.event_view(rec), 201)


@bp.route("/eld/duty-events/<id>", methods=["GET"])
def get_event(id):
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    rec = db.duty_events.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Duty event not found.")
    return response.object_response(ser.event_view(rec), 200)


@bp.route("/eld/duty-events", methods=["GET"])
def list_events():
    _, role = get_auth()
    require_role(role, {"Driver", "CarrierAdmin", "SafetyOfficer"})
    limit, offset = val.get_pagination()
    items = list(db.duty_events.values())
    driver_id = request.args.get("driver_id")
    device_id = request.args.get("device_id")
    vehicle_id = request.args.get("vehicle_id")
    record_status = request.args.get("record_status")
    edited_from = request.args.get("edited_from_event_id")
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if device_id is not None:
        items = [r for r in items if r["device_id"] == device_id]
    if vehicle_id is not None:
        items = [r for r in items if r["vehicle_id"] == vehicle_id]
    if record_status is not None:
        items = [r for r in items if r["record_status"] == record_status]
    if edited_from is not None:
        items = [r for r in items if r["edited_from_event_id"] == edited_from]
    page, total = paginate(items, limit, offset)
    return response.array_response([ser.event_view(r) for r in page], limit, offset, total)


@bp.route("/eld/duty-events/<id>/mark-error", methods=["POST"])
def mark_error(id):
    _, role = get_auth()
    require_role(role, {"CarrierAdmin"})
    rec = db.duty_events.get(id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Duty event not found.")
    body = val.get_body()

    # state: must be ACTIVE
    if rec["record_status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Event is not ACTIVE.")

    if "expected_dutystatusevent_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "expected_dutystatusevent_version is required.")
    if body["expected_dutystatusevent_version"] != rec["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Event version mismatch.")

    rec["record_status"] = "INACTIVE_ERROR"
    model.touch(rec)

    driver = db.drivers.get(rec["driver_id"])
    if driver is not None:
        hos.recompute_driver(driver, dismiss_note=hos.NOTE_CORRECTED)
    return response.object_response(ser.event_view(rec), 200)
