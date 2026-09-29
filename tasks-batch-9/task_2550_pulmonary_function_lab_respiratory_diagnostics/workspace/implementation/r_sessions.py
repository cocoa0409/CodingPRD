"""Test sessions, maneuvers, quality finalization and chain of custody."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import services as svc
from auth import (authenticate, ALL_ROLES, LAB_MANAGER, TECHNOLOGIST,
                  INTERPRETING_PHYSICIAN, COMPLIANCE_AUDITOR)
from calc import D, num, rnd, rnd_int
from errors import ApiError
from responses import object_response, paginate
from store import (db, iso, parse_date, parse_iso, stamp_new, stamp_event,
                   touch)
import validation as v

bp = Blueprint("sessions", __name__)

PHASES = ["PRE_BD", "POST_BD", "CHALLENGE_BASELINE", "POST_CHALLENGE"]
ACCEPTABILITIES = ["ACCEPTABLE", "USABLE_FEV1_ONLY", "UNACCEPTABLE"]
CUSTODY_EVENT_TYPES = ["ID_VERIFIED", "SEAL_APPLIED", "SEAL_BROKEN",
                       "WITNESS_SIGNED"]
ID_DOCUMENT_TYPES = ["PHOTO_ID", "PASSPORT", "EMPLOYEE_BADGE"]
FLOOR_READ_ROLES = [LAB_MANAGER, TECHNOLOGIST, INTERPRETING_PHYSICIAN,
                    COMPLIANCE_AUDITOR]
SESSION_TERMINAL = ("REPORTED", "ABORTED")


def _competency_current(staff):
    expires = parse_date(staff.get("competency_expires_on"))
    return expires is not None and expires >= db.clock.date()


def _check_technologist(staff, device):
    if device["modality"] not in (staff.get("credentialed_modalities") or []) \
            or not _competency_current(staff):
        raise ApiError("ERR_TECH_NOT_QUALIFIED",
                       "The technologist is not credentialed and current for "
                       "%s." % device["modality"])


# ------------------------------------------------------------------ scheduling

def _device_window_conflict(device_id, start, end, exclude_id=None):
    allowance = timedelta(minutes=calc.DEVICE_TURNAROUND_MINUTES)
    new_end = end + allowance
    for session in db.sessions.values():
        if session["device_id"] != device_id:
            continue
        if session["id"] == exclude_id:
            continue
        if session["session_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = parse_iso(session["scheduled_start_at"])
        other_end = parse_iso(session["scheduled_end_at"]) + allowance
        if start < other_end and other_start < new_end:
            return True
    return False


def _technologist_window_count(staff_id, start, end, exclude_id=None):
    count = 0
    for session in db.sessions.values():
        if session["technologist_staff_id"] != staff_id:
            continue
        if session["id"] == exclude_id:
            continue
        if session["session_status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        other_start = parse_iso(session["scheduled_start_at"])
        other_end = parse_iso(session["scheduled_end_at"])
        if start <= other_end and other_start <= end:
            count += 1
    return count


@bp.route("/test-sessions", methods=["POST"])
def create_session():
    actor = authenticate([TECHNOLOGIST])
    body = v.get_body()
    order = None
    device = None
    if body.get("order_id") is not None:
        order = svc.get_order(body.get("order_id"))
    if body.get("device_id") is not None:
        device = svc.get_device(body.get("device_id"))
    if order is None:
        v.v_str(body, "order_id")
    if device is None:
        v.v_str(body, "device_id")
    start = v.v_datetime(body, "scheduled_start_at")
    end = v.v_datetime(body, "scheduled_end_at")
    if not end > start:
        raise v.bad("scheduled_end_at must be strictly after "
                    "scheduled_start_at.")

    if order["status"] != "READY":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Only a READY order may be scheduled.")
    if device["status"] != "AVAILABLE":
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE",
                       "The device is not AVAILABLE.")
    if device["modality"] not in order["requested_modalities"]:
        raise ApiError("ERR_DEVICE_MODALITY_MISMATCH",
                       "The device modality was not requested on the order.")
    _check_technologist(actor.staff, device)
    if not svc.has_same_day_pass_calibration(device):
        raise ApiError("ERR_CALIBRATION_STALE",
                       "The device has no passing volume calibration today.")
    if device.get("last_biologic_control_date") != \
            svc.iso_date(db.clock.date()) or \
            int(device.get("consecutive_biologic_failures") or 0) != 0:
        raise ApiError("ERR_BIOLOGIC_CONTROL_MISSING",
                       "The device has no current biologic control survey.")
    if not svc.infection_control_satisfied(device):
        raise ApiError("ERR_INFECTION_CONTROL_INCOMPLETE",
                       "The infection-control cycle is not complete.")
    if device["modality"] in ("DLCO", "PLETHYSMOGRAPHY") and \
            not svc.has_same_day_leak_check(device):
        raise ApiError("ERR_LEAK_CHECK_MISSING",
                       "The device has no completed leak check today.")
    for hold in svc.order_holds(order["id"]):
        if hold["status"] == "SUPERSEDED":
            continue
        if hold["status"] != "ATTESTED":
            raise ApiError("ERR_MED_HOLD_VIOLATED",
                           "Every non-superseded medication hold must be "
                           "ATTESTED.")
    release_at = parse_iso(order.get("hold_release_at"))
    if release_at is not None and db.clock < release_at:
        raise ApiError("ERR_MED_HOLD_NOT_ELAPSED",
                       "The medication hold window has not elapsed.")
    if _device_window_conflict(device["id"], start, end):
        raise ApiError("ERR_DEVICE_WINDOW_CONFLICT",
                       "The device is already committed during that window.")
    if _technologist_window_count(actor.staff_id, start, end) >= \
            calc.TECH_MAX_CONCURRENT_SESSIONS:
        raise ApiError("ERR_TECHNOLOGIST_WINDOW_CONFLICT",
                       "The technologist is already committed during that "
                       "window.")
    patient = db.patients.get(order["patient_id"])
    equation = svc.select_reference_equation(device, patient)
    predicted_fev1, predicted_fvc, lln_fev1 = calc.predicted_values(
        equation, patient["height_cm"], svc.age_years_of(patient))

    record = {
        "order_id": order["id"],
        "device_id": device["id"],
        "technologist_staff_id": actor.staff_id,
        "reference_equation_id": equation["id"],
        "scheduled_start_at": iso(start),
        "scheduled_end_at": iso(end),
        "session_status": "SCHEDULED",
        "custody_status": ("NOT_APPLICABLE"
                           if order["test_context"] == "ROUTINE_CLINICAL"
                           else "CUSTODY_OPEN"),
        "reference_equation_code": equation["equation_code"],
        "predicted_fev1_l": num(predicted_fev1),
        "predicted_fvc_l": num(predicted_fvc),
        "lln_fev1_l": num(lln_fev1),
        "ratio_lln": equation["ratio_lln"],
        "best_fev1_l": None,
        "best_fvc_l": None,
        "best_fev1_post_l": None,
        "acceptable_maneuver_count": 0,
        "repeatability_delta_ml": None,
        "fvc_repeatability_delta_ml": None,
        "quality_grade": "F",
        "fev1_pct_predicted": None,
        "fvc_pct_predicted": None,
        "fev1_fvc_ratio": None,
        "bd_response_pct": None,
        "bd_response_ml": None,
        "bd_response_variant": None,
        "bd_response_positive": None,
        "rejection_round": 0,
        "abort_reason": None,
        "turnaround_minutes": None,
        "technologist_comment": None,
    }
    stamp_new(record)
    db.sessions[record["id"]] = record
    order["status"] = "IN_TESTING"
    touch(order)
    return object_response(svc.ser_session(record), 201)


@bp.route("/test-sessions/<session_id>", methods=["GET"])
def read_session(session_id):
    authenticate(ALL_ROLES)
    return object_response(svc.ser_session(svc.get_session(session_id)))


@bp.route("/test-sessions", methods=["GET"])
def list_sessions():
    authenticate(ALL_ROLES)
    filters = {
        "order_id": request.args.get("order_id"),
        "device_id": request.args.get("device_id"),
        "technologist_staff_id": request.args.get("technologist_staff_id"),
        "reference_equation_id": request.args.get("reference_equation_id"),
        "session_status": request.args.get("session_status"),
        "custody_status": request.args.get("custody_status"),
    }
    records = []
    for session in db.sessions.values():
        keep = True
        for field, wanted in filters.items():
            if wanted is not None and session.get(field) != wanted:
                keep = False
                break
        if keep:
            records.append(session)
    return paginate(records, svc.ser_session)


# ------------------------------------------------------------------ maneuvers

@bp.route("/test-sessions/<session_id>/maneuvers", methods=["POST"])
def create_maneuver(session_id):
    actor = authenticate([TECHNOLOGIST])
    session = svc.get_session(session_id)
    if session["technologist_staff_id"] != actor.staff_id:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Only the technologist named on the study may append "
                       "maneuvers.")
    body = v.get_body()
    phase = v.v_enum(body, "phase", PHASES)
    fvc_l = v.v_num(body, "fvc_l", minimum=0, maximum=10.000,
                    exclusive_min=True)
    fev1_l = v.v_num(body, "fev1_l", minimum=0, maximum=10.000,
                     exclusive_min=True)
    if D(fev1_l) > D(fvc_l):
        raise v.bad("fev1_l may not exceed fvc_l.")
    pef = v.v_num(body, "pef_l_s")
    bev = v.v_int(body, "back_extrapolated_volume_ml")
    expiratory_time_s = v.v_num(body, "expiratory_time_s", minimum=0,
                                exclusive_min=True)
    plateau = v.v_bool(body, "plateau_reached")
    cough = v.v_bool(body, "cough_in_first_second")
    glottic = v.v_bool(body, "glottic_closure")
    coaching_note = v.v_str(body, "coaching_note", required=False)

    if session["session_status"] not in ("SCHEDULED", "IN_PROGRESS",
                                         "REJECTED"):
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "Maneuvers may only be appended while the study is "
                       "SCHEDULED, IN_PROGRESS or REJECTED.")
    device = db.devices.get(session["device_id"])
    if device is None or device["status"] != "AVAILABLE":
        raise ApiError("ERR_DEVICE_NOT_AVAILABLE",
                       "The device is not AVAILABLE.")
    if session["session_status"] == "REJECTED" and \
            int(session.get("rejection_round") or 0) >= \
            calc.MAX_REJECTION_ROUNDS:
        raise ApiError("ERR_MAX_REJECTION_ROUNDS_EXCEEDED",
                       "The coaching cycle for this study is closed.")
    _check_technologist(actor.staff, device)

    bev_limit_ml, acceptability, reasons = calc.maneuver_acceptability(
        fvc_l, bev, expiratory_time_s, plateau, cough, glottic)
    if acceptability == "UNACCEPTABLE" and (coaching_note is None
                                            or coaching_note.strip() == ""):
        raise ApiError("ERR_COACHING_NOTE_REQUIRED",
                       "An unacceptable maneuver requires a coaching note.")

    index = len(svc.session_maneuvers(session["id"])) + 1
    record = {
        "session_id": session["id"],
        "maneuver_index": index,
        "phase": phase,
        "fvc_l": fvc_l,
        "fev1_l": fev1_l,
        "pef_l_s": pef,
        "back_extrapolated_volume_ml": bev,
        "expiratory_time_s": expiratory_time_s,
        "plateau_reached": bool(plateau),
        "cough_in_first_second": bool(cough),
        "glottic_closure": bool(glottic),
        "acceptability": acceptability,
        "bev_limit_ml": bev_limit_ml,
        "rejection_reasons": reasons,
        "coaching_note": coaching_note,
        "performed_at": iso(db.clock),
    }
    stamp_event(record)
    db.maneuvers[record["id"]] = record
    session["session_status"] = "IN_PROGRESS"
    svc.recompute_session_quality(session)
    touch(session)
    return object_response(svc.ser_maneuver(record), 201)


@bp.route("/test-sessions/<session_id>/maneuvers", methods=["GET"])
def list_session_maneuvers(session_id):
    authenticate(FLOOR_READ_ROLES)
    session = svc.get_session(session_id)
    phase = request.args.get("phase")
    acceptability = request.args.get("acceptability")
    records = []
    for maneuver in svc.session_maneuvers(session["id"]):
        if phase is not None and maneuver["phase"] != phase:
            continue
        if acceptability is not None and \
                maneuver["acceptability"] != acceptability:
            continue
        records.append(maneuver)
    return paginate(records, svc.ser_maneuver)


@bp.route("/maneuvers/<maneuver_id>", methods=["GET"])
def read_maneuver(maneuver_id):
    authenticate(FLOOR_READ_ROLES)
    return object_response(svc.ser_maneuver(svc.get_maneuver(maneuver_id)))


@bp.route("/maneuvers", methods=["GET"])
def list_maneuvers():
    authenticate(FLOOR_READ_ROLES)
    session_id = request.args.get("session_id")
    phase = request.args.get("phase")
    acceptability = request.args.get("acceptability")
    records = []
    for maneuver in db.maneuvers.values():
        if session_id is not None and maneuver["session_id"] != session_id:
            continue
        if phase is not None and maneuver["phase"] != phase:
            continue
        if acceptability is not None and \
                maneuver["acceptability"] != acceptability:
            continue
        records.append(maneuver)
    return paginate(records, svc.ser_maneuver)


# ---------------------------------------------------------- quality finalization

@bp.route("/test-sessions/<session_id>/finalize-quality", methods=["POST"])
def finalize_quality(session_id):
    authenticate([TECHNOLOGIST])
    session = svc.get_session(session_id)
    body = v.get_body()
    comment = v.v_str(body, "technologist_comment", required=False)
    if session["session_status"] != "IN_PROGRESS":
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "Only an IN_PROGRESS study may be finalized.")
    live_runs = [r for r in db.runs.values()
                 if r["session_id"] == session["id"]
                 and r["status"] in ("ARMED", "IN_PROGRESS")]
    if live_runs:
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "A challenge run on this study is still live.")
    session["technologist_comment"] = comment
    device = db.devices.get(session["device_id"])
    order = db.orders.get(session["order_id"])
    if session["quality_grade"] in ("A", "B", "C"):
        session["session_status"] = "ACCEPTED"
        if order is not None:
            svc.apply_bronchodilator_response(session, order)
        touch(session)
        if device is not None:
            svc.close_device_after_session(device, session)
    else:
        session["rejection_round"] = int(
            session.get("rejection_round") or 0) + 1
        session["session_status"] = "REJECTED"
        touch(session)
        if session["rejection_round"] >= calc.MAX_REJECTION_ROUNDS and \
                device is not None:
            svc.close_device_after_session(device, session)
    return object_response(svc.ser_session(session), 200)


# ------------------------------------------------------------- chain of custody

CUSTODY_SEQUENCE = {
    "ID_VERIFIED": ("CUSTODY_OPEN", "CUSTODY_ID_VERIFIED"),
    "SEAL_APPLIED": ("CUSTODY_ID_VERIFIED", "CUSTODY_SEALED"),
    "SEAL_BROKEN": ("CUSTODY_SEALED", "CUSTODY_BROKEN"),
}


def _peek_event_type():
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        value = body.get("event_type")
        if isinstance(value, str):
            return value
    return None


@bp.route("/test-sessions/<session_id>/custody-events", methods=["POST"])
def create_custody_event(session_id):
    actor = authenticate([TECHNOLOGIST, COMPLIANCE_AUDITOR])
    peeked = _peek_event_type()
    if peeked == "WITNESS_SIGNED" and actor.role != COMPLIANCE_AUDITOR:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "The witness attestation is reserved to "
                       "ComplianceAuditor.")
    if peeked in CUSTODY_SEQUENCE and actor.role != TECHNOLOGIST:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Only the technologist may append %s." % peeked)
    session = svc.get_session(session_id)
    body = v.get_body()
    event_type = v.v_enum(body, "event_type", CUSTODY_EVENT_TYPES)
    seal_serial = v.v_str(body, "seal_serial", required=False)
    id_document_type = v.v_enum(body, "id_document_type", ID_DOCUMENT_TYPES,
                                required=False)
    note = v.v_str(body, "note", required=False)

    needs_seal = event_type in ("SEAL_APPLIED", "SEAL_BROKEN")
    needs_document = event_type == "ID_VERIFIED"
    if needs_seal and seal_serial is None:
        raise ApiError("ERR_MISSING_EVENT_FIELDS",
                       "seal_serial is required for %s." % event_type)
    if not needs_seal and seal_serial is not None:
        raise ApiError("ERR_MISSING_EVENT_FIELDS",
                       "seal_serial is not permitted for %s." % event_type)
    if needs_document and id_document_type is None:
        raise ApiError("ERR_MISSING_EVENT_FIELDS",
                       "id_document_type is required for %s." % event_type)
    if not needs_document and id_document_type is not None:
        raise ApiError("ERR_MISSING_EVENT_FIELDS",
                       "id_document_type is not permitted for %s."
                       % event_type)

    if session["session_status"] in SESSION_TERMINAL:
        raise ApiError("ERR_SESSION_STATE_INVALID",
                       "The study is no longer accepting custody events.")
    if session["custody_status"] == "NOT_APPLICABLE":
        raise ApiError("ERR_CUSTODY_NOT_APPLICABLE",
                       "Chain of custody is not applicable to this study.")
    if event_type in CUSTODY_SEQUENCE:
        required_from, next_status = CUSTODY_SEQUENCE[event_type]
        if session["custody_status"] != required_from:
            raise ApiError("ERR_CUSTODY_SEQUENCE_INVALID",
                           "%s requires custody_status %s."
                           % (event_type, required_from))
    else:
        next_status = None

    record = {
        "session_id": session["id"],
        "event_type": event_type,
        "actor_user_id": actor.user_id,
        "actor_role": actor.role,
        "seal_serial": seal_serial,
        "id_document_type": id_document_type,
        "note": note,
        "performed_at": iso(db.clock),
    }
    stamp_event(record)
    db.custody_events[record["id"]] = record
    if next_status is not None:
        session["custody_status"] = next_status
    touch(session)
    return object_response(svc.ser_custody_event(record), 201)


@bp.route("/test-sessions/<session_id>/custody-events", methods=["GET"])
def list_session_custody_events(session_id):
    authenticate(FLOOR_READ_ROLES)
    session = svc.get_session(session_id)
    event_type = request.args.get("event_type")
    records = []
    for event in db.custody_events.values():
        if event["session_id"] != session["id"]:
            continue
        if event_type is not None and event["event_type"] != event_type:
            continue
        records.append(event)
    return paginate(records, svc.ser_custody_event)


@bp.route("/custody-events/<event_id>", methods=["GET"])
def read_custody_event(event_id):
    authenticate(FLOOR_READ_ROLES)
    return object_response(svc.ser_custody_event(
        svc.get_custody_event(event_id)))


@bp.route("/custody-events", methods=["GET"])
def list_custody_events():
    authenticate(FLOOR_READ_ROLES)
    session_id = request.args.get("session_id")
    event_type = request.args.get("event_type")
    actor_user_id = request.args.get("actor_user_id")
    records = []
    for event in db.custody_events.values():
        if session_id is not None and event["session_id"] != session_id:
            continue
        if event_type is not None and event["event_type"] != event_type:
            continue
        if actor_user_id is not None and \
                event["actor_user_id"] != actor_user_id:
            continue
        records.append(event)
    return paginate(records, svc.ser_custody_event)
