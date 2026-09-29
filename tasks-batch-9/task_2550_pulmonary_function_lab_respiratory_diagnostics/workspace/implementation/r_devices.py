"""Devices, the device quality log and quarantine clearance."""
from flask import Blueprint, request

import calc
import services as svc
from auth import (authenticate, ALL_ROLES, LAB_MANAGER, TECHNOLOGIST,
                  INTERPRETING_PHYSICIAN, COMPLIANCE_AUDITOR)
from calc import D, num, rnd
from errors import ApiError
from responses import object_response, paginate
from store import db, iso, iso_date, parse_date, parse_iso, stamp_new, \
    stamp_event, touch
import validation as v

bp = Blueprint("devices", __name__)

EVENT_TYPES = ["VOLUME_CALIBRATION", "LEAK_CHECK", "BIOLOGIC_CONTROL",
               "FILTER_REPLACEMENT", "HIGH_LEVEL_DISINFECT"]

REQUIRED_BY_TYPE = {
    "VOLUME_CALIBRATION": ["measured_volume_l", "ambient_temp_c",
                           "barometric_pressure_kpa"],
    "LEAK_CHECK": ["ambient_temp_c", "barometric_pressure_kpa"],
    "BIOLOGIC_CONTROL": ["subject_staff_id", "measured_fev1_l",
                         "measured_fvc_l"],
    "FILTER_REPLACEMENT": ["filter_serial"],
    "HIGH_LEVEL_DISINFECT": ["dwell_minutes"],
}

CONDITIONAL_FIELDS = ["measured_volume_l", "ambient_temp_c",
                      "barometric_pressure_kpa", "subject_staff_id",
                      "measured_fev1_l", "measured_fvc_l", "filter_serial",
                      "dwell_minutes"]

QUALITY_READ_ROLES = [LAB_MANAGER, TECHNOLOGIST, INTERPRETING_PHYSICIAN,
                      COMPLIANCE_AUDITOR]


# --------------------------------------------------------------------- devices

@bp.route("/devices", methods=["POST"])
def create_device():
    authenticate([LAB_MANAGER])
    body = v.get_body()
    device_code = v.v_str(body, "device_code")
    modality = v.v_enum(body, "modality", calc.MODALITIES)
    for existing in db.devices.values():
        if existing["device_code"] == device_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "device_code already exists.")
    record = {
        "device_code": device_code,
        "modality": modality,
        "status": "NEW",
        "last_calibration_at": None,
        "last_calibration_error_pct": None,
        "last_biologic_control_date": None,
        "consecutive_biologic_failures": 0,
        "last_session_end_at": None,
        "current_filter_serial": None,
        "sessions_since_filter_change": 0,
        "quarantined_at": None,
        "quarantine_reason": None,
        "quarantine_trigger_staff_id": None,
    }
    stamp_new(record)
    db.devices[record["id"]] = record
    return object_response(svc.ser_device(record), 201)


@bp.route("/devices/<device_id>", methods=["GET"])
def read_device(device_id):
    authenticate(ALL_ROLES)
    return object_response(svc.ser_device(svc.get_device(device_id)))


@bp.route("/devices", methods=["GET"])
def list_devices():
    authenticate(ALL_ROLES)
    status = request.args.get("status")
    modality = request.args.get("modality")
    trigger = request.args.get("quarantine_trigger_staff_id")
    records = []
    for device in db.devices.values():
        if status is not None and device["status"] != status:
            continue
        if modality is not None and device["modality"] != modality:
            continue
        if trigger is not None and \
                device.get("quarantine_trigger_staff_id") != trigger:
            continue
        records.append(device)
    return paginate(records, svc.ser_device)


# -------------------------------------------------------------- quality events

def _validate_event_shape(body):
    event_type = v.v_enum(body, "event_type", EVENT_TYPES)
    v.v_str(body, "note", required=False)
    v.v_num(body, "measured_volume_l", required=False, minimum=0,
            exclusive_min=True)
    v.v_num(body, "measured_fev1_l", required=False, minimum=0,
            exclusive_min=True)
    v.v_num(body, "measured_fvc_l", required=False, minimum=0,
            exclusive_min=True)
    if body.get("ambient_temp_c") is not None and \
            not v.is_number(body["ambient_temp_c"]):
        raise v.bad("Field 'ambient_temp_c' must be a number.")
    if body.get("barometric_pressure_kpa") is not None and \
            not v.is_number(body["barometric_pressure_kpa"]):
        raise v.bad("Field 'barometric_pressure_kpa' must be a number.")
    v.v_str(body, "filter_serial", required=False)
    v.v_int(body, "dwell_minutes", required=False)
    if body.get("subject_staff_id") is not None and \
            not isinstance(body["subject_staff_id"], str):
        raise v.bad("Field 'subject_staff_id' must be a string.")
    return event_type


def _check_event_field_set(body, event_type):
    required = REQUIRED_BY_TYPE[event_type]
    for field in required:
        if body.get(field) is None:
            raise ApiError("ERR_MISSING_EVENT_FIELDS",
                           "Field '%s' is required for %s."
                           % (field, event_type))
    for field in CONDITIONAL_FIELDS:
        if field in required:
            continue
        if body.get(field) is not None:
            raise ApiError("ERR_MISSING_EVENT_FIELDS",
                           "Field '%s' is not permitted for %s."
                           % (field, event_type))


def _check_ambient(body):
    temp = body.get("ambient_temp_c")
    if not isinstance(temp, int) or isinstance(temp, bool):
        if not (isinstance(temp, float) and float(temp).is_integer()):
            raise ApiError("ERR_AMBIENT_OUT_OF_RANGE",
                           "ambient_temp_c must be a whole number.")
    temp = int(temp)
    if temp < calc.AMBIENT_TEMP_MIN_C or temp > calc.AMBIENT_TEMP_MAX_C:
        raise ApiError("ERR_AMBIENT_OUT_OF_RANGE",
                       "ambient_temp_c must be between %d and %d inclusive."
                       % (calc.AMBIENT_TEMP_MIN_C, calc.AMBIENT_TEMP_MAX_C))
    baro = D(body.get("barometric_pressure_kpa"))
    if baro < calc.BAROMETRIC_MIN_KPA or baro > calc.BAROMETRIC_MAX_KPA:
        raise ApiError("ERR_AMBIENT_OUT_OF_RANGE",
                       "barometric_pressure_kpa must be between 80.00 and "
                       "110.00 inclusive.")


def _new_event(device, actor, event_type, body):
    record = {
        "device_id": device["id"],
        "event_type": event_type,
        "performed_by_staff_id": actor.staff_id,
        "subject_staff_id": body.get("subject_staff_id"),
        "measured_volume_l": body.get("measured_volume_l"),
        "ambient_temp_c": (int(body["ambient_temp_c"])
                           if body.get("ambient_temp_c") is not None else None),
        "barometric_pressure_kpa": body.get("barometric_pressure_kpa"),
        "measured_fev1_l": body.get("measured_fev1_l"),
        "measured_fvc_l": body.get("measured_fvc_l"),
        "filter_serial": body.get("filter_serial"),
        "dwell_minutes": body.get("dwell_minutes"),
        "btps_factor": None,
        "corrected_volume_l": None,
        "error_pct": None,
        "deviation_pct": None,
        "deviation_variant": None,
        "rolling_mean_fev1_l": None,
        "outcome": None,
        "failure_reason": None,
        "performed_at": iso(db.clock),
        "note": body.get("note"),
    }
    return record


def _apply_volume_calibration(device, event, actor):
    btps, corrected, error_pct, outcome = calc.calibration_result(
        event["measured_volume_l"], event["ambient_temp_c"],
        event["barometric_pressure_kpa"])
    event["btps_factor"] = num(btps)
    event["corrected_volume_l"] = num(corrected)
    event["error_pct"] = num(error_pct)
    event["outcome"] = outcome
    device["last_calibration_error_pct"] = num(error_pct)
    if outcome == "PASS":
        event["failure_reason"] = None
        device["last_calibration_at"] = event["performed_at"]
        if device["status"] == "NEW":
            device["status"] = "AVAILABLE"
        touch(device)
    else:
        event["failure_reason"] = "CAL_TOLERANCE_EXCEEDED"
        svc.quarantine_device(device, "CALIBRATION_FAILED", actor.staff_id)
        touch(device)
        svc.cascade_device_quarantine(device)


def _biologic_comparator(device, event, subject):
    established = parse_date(subject.get("baseline_established_on"))
    baseline_age_days = None
    if established is not None:
        baseline_age_days = (db.clock.date() - established).days
    if baseline_age_days is not None and \
            baseline_age_days > calc.BASELINE_VALIDITY_DAYS:
        prior = [e for e in db.quality_events.values()
                 if e["device_id"] == device["id"]
                 and e["event_type"] == "BIOLOGIC_CONTROL"
                 and e.get("subject_staff_id") == subject["id"]
                 and e.get("outcome") in ("PASS", "WARN")]
        prior.sort(key=lambda e: (e["performed_at"], e["created_at"],
                                  e.get("_seq") or 0), reverse=True)
        window = prior[:calc.ROLLING_WINDOW_SIZE]
        if len(window) == calc.ROLLING_WINDOW_SIZE:
            mean = calc.rolling_mean([e["measured_fev1_l"] for e in window])
            return "ROLLING_MEAN", mean
    return "ABSOLUTE_BASELINE", D(subject.get("baseline_fev1_l"))


def _apply_biologic_control(device, event, actor, subject):
    variant, comparator = _biologic_comparator(device, event, subject)
    deviation, outcome = calc.biologic_deviation(event["measured_fev1_l"],
                                                 comparator)
    event["deviation_variant"] = variant
    event["rolling_mean_fev1_l"] = (num(comparator)
                                    if variant == "ROLLING_MEAN" else None)
    event["deviation_pct"] = num(deviation)
    event["outcome"] = outcome
    performed_date = iso_date(parse_iso(event["performed_at"]).date())
    if outcome == "PASS":
        device["last_biologic_control_date"] = performed_date
        device["consecutive_biologic_failures"] = 0
        touch(device)
    elif outcome == "WARN":
        device["last_biologic_control_date"] = performed_date
        touch(device)
    else:
        event["failure_reason"] = "BCS_DEVIATION_EXCEEDED"
        device["consecutive_biologic_failures"] = int(
            device.get("consecutive_biologic_failures") or 0) + 1
        svc.quarantine_device(device, "BIOLOGIC_CONTROL_FAILED",
                              actor.staff_id)
        touch(device)
        svc.cascade_device_quarantine(device)


@bp.route("/devices/<device_id>/quality-events", methods=["POST"])
def create_quality_event(device_id):
    actor = authenticate([TECHNOLOGIST])
    device = svc.get_device(device_id)
    body = v.get_body()
    subject = None
    if body.get("subject_staff_id") is not None:
        subject = svc.get_staff(body.get("subject_staff_id"))
    event_type = _validate_event_shape(body)
    _check_event_field_set(body, event_type)
    if event_type in ("VOLUME_CALIBRATION", "LEAK_CHECK"):
        _check_ambient(body)
    if event_type == "FILTER_REPLACEMENT":
        if body["filter_serial"] == device.get("current_filter_serial"):
            raise ApiError("ERR_FILTER_SERIAL_REUSED",
                           "filter_serial matches the fitted filter.")
    if event_type == "BIOLOGIC_CONTROL":
        if subject["id"] == actor.staff_id:
            raise ApiError("ERR_SELF_BIOLOGIC_CONTROL",
                           "A technologist may not be their own biologic "
                           "control subject.")
        if not subject.get("is_biologic_control") or \
                subject.get("baseline_fev1_l") is None:
            raise ApiError("ERR_SELF_BIOLOGIC_CONTROL",
                           "The nominated subject is not enrolled as a "
                           "biologic control with a stored baseline.")

    event = _new_event(device, actor, event_type, body)
    if event_type == "VOLUME_CALIBRATION":
        _apply_volume_calibration(device, event, actor)
    elif event_type == "LEAK_CHECK":
        event["outcome"] = "COMPLETE"
    elif event_type == "BIOLOGIC_CONTROL":
        _apply_biologic_control(device, event, actor, subject)
    elif event_type == "FILTER_REPLACEMENT":
        event["outcome"] = "COMPLETE"
        device["current_filter_serial"] = event["filter_serial"]
        device["sessions_since_filter_change"] = 0
    else:
        if int(event["dwell_minutes"]) >= calc.MIN_DWELL_MINUTES:
            event["outcome"] = "COMPLETE"
        else:
            event["outcome"] = "INCOMPLETE"
            event["failure_reason"] = "DWELL_TIME_SHORT"

    stamp_event(event)
    db.quality_events[event["id"]] = event

    if event_type == "FILTER_REPLACEMENT":
        svc.maybe_return_soiled_device(device)
        touch(device)
    elif event_type == "HIGH_LEVEL_DISINFECT" and event["outcome"] == "COMPLETE":
        if svc.maybe_return_soiled_device(device):
            touch(device)
    return object_response(svc.ser_quality_event(event), 201)


@bp.route("/device-quality-events/<event_id>", methods=["GET"])
def read_quality_event(event_id):
    authenticate(QUALITY_READ_ROLES)
    return object_response(svc.ser_quality_event(
        svc.get_quality_event(event_id)))


@bp.route("/device-quality-events", methods=["GET"])
def list_quality_events():
    authenticate(QUALITY_READ_ROLES)
    filters = {
        "device_id": request.args.get("device_id"),
        "subject_staff_id": request.args.get("subject_staff_id"),
        "performed_by_staff_id": request.args.get("performed_by_staff_id"),
        "event_type": request.args.get("event_type"),
        "outcome": request.args.get("outcome"),
    }
    records = []
    for event in db.quality_events.values():
        keep = True
        for field, wanted in filters.items():
            if wanted is not None and event.get(field) != wanted:
                keep = False
                break
        if keep:
            records.append(event)
    return paginate(records, svc.ser_quality_event)


@bp.route("/devices/<device_id>/return-to-service", methods=["POST"])
def return_to_service(device_id):
    authenticate([LAB_MANAGER])
    device = svc.get_device(device_id)
    body = v.get_body()
    clearance_note = v.v_str(body, "clearance_note")
    if device["status"] != "QUARANTINED":
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE",
                       "Only a QUARANTINED device can be returned to service.")
    if not svc.infection_control_satisfied(device):
        raise ApiError("ERR_INFECTION_CONTROL_INCOMPLETE",
                       "The infection-control cycle is not complete.")
    boundary = parse_iso(device.get("quarantined_at"))
    calibration = [e for e in svc.device_events(device["id"],
                                                "VOLUME_CALIBRATION", ("PASS",))
                   if parse_iso(e["performed_at"]) > boundary]
    biologic = [e for e in svc.device_events(device["id"], "BIOLOGIC_CONTROL",
                                             ("PASS",))
                if parse_iso(e["performed_at"]) > boundary]
    if not calibration or not biologic or \
            int(device.get("consecutive_biologic_failures") or 0) != 0:
        raise ApiError("ERR_QUARANTINE_CLEARANCE_INCOMPLETE",
                       "The quarantine clearance evidence is incomplete.")
    trigger = device.get("quarantine_trigger_staff_id")
    if trigger is not None:
        independent_cal = [e for e in calibration
                           if e.get("performed_by_staff_id") != trigger]
        independent_bio = [e for e in biologic
                           if e.get("performed_by_staff_id") != trigger]
        if not independent_cal or not independent_bio:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The clearing evidence may not be produced by the "
                           "staff member whose failure caused the quarantine.")
    device["status"] = "AVAILABLE"
    device["quarantined_at"] = None
    device["quarantine_reason"] = None
    device["quarantine_trigger_staff_id"] = None
    touch(device)
    return object_response(svc.ser_device(device), 200)
