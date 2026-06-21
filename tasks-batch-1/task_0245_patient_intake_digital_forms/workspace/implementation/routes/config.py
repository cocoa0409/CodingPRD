"""Configuration-root routes: clock, clinics, providers, exam-rooms, patients,
appointments (PRD §3.1, §3.2; §3.12 clock).
"""
from flask import Blueprint, request

import clock
import db
import serialize
from errors import err, ERR_INVALID_REQUEST, ERR_PROVIDER_DOUBLE_BOOKED
from middleware import require_roles
from response import success, success_list
from services import calculations
from services.common import touch, require_string, require_int, opt_int
from services.lookups import get_clinic, get_provider, get_patient
from services.pagination import paginate
from services.sessions import run_sweep

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------
# Deterministic clock (PRD §3.12)
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ClinicAdmin")
def set_current_utc():
    body = request.get_json(silent=True) or {}
    clinic_id = require_string(body, "clinic_id")
    to_iso = require_string(body, "to_iso8601")
    clinic = get_clinic(clinic_id)
    instant = clock.parse_instant(to_iso)
    with db.LOCK:
        clinic["current_utc"] = clock.format_instant(instant)
        touch(clinic)
        run_sweep(clinic)
    return success(serialize.clinic(clinic), status=200)


# --------------------------------------------------------------------------
# Clinic (PRD §3.1)
# --------------------------------------------------------------------------
@bp.route("/clinics", methods=["POST"])
@require_roles("ClinicAdmin")
def create_clinic():
    body = request.get_json(silent=True) or {}
    name = require_string(body, "name")
    timezone = body.get("timezone") if body.get("timezone") is not None else "UTC"
    if not isinstance(timezone, str):
        raise err(ERR_INVALID_REQUEST, "timezone must be a string")

    form_expiration_hours = opt_int(body, "form_expiration_hours", 72)
    if form_expiration_hours <= 0:
        raise err(ERR_INVALID_REQUEST, "form_expiration_hours must be > 0")

    reminder_quiet_start_min = opt_int(body, "reminder_quiet_start_min", 1320)
    reminder_quiet_end_min = opt_int(body, "reminder_quiet_end_min", 420)
    reminder_min_gap_minutes = opt_int(body, "reminder_min_gap_minutes", 240)
    if reminder_min_gap_minutes <= 0:
        raise err(ERR_INVALID_REQUEST, "reminder_min_gap_minutes must be > 0")

    copay_rounding = body.get("copay_rounding")
    if copay_rounding is None:
        copay_rounding = "PER_LINE_THEN_SUM"
    if copay_rounding not in {"PER_LINE_THEN_SUM", "SUM_THEN_ROUND"}:
        raise err(ERR_INVALID_REQUEST, "invalid copay_rounding")

    facility_fee_cents = opt_int(body, "facility_fee_cents", 0)
    if facility_fee_cents < 0:
        raise err(ERR_INVALID_REQUEST, "facility_fee_cents must be non-negative")

    now = db.now_iso()
    clinic = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "name": name,
        "timezone": timezone,
        "form_expiration_hours": form_expiration_hours,
        "reminder_quiet_start_min": reminder_quiet_start_min,
        "reminder_quiet_end_min": reminder_quiet_end_min,
        "reminder_min_gap_minutes": reminder_min_gap_minutes,
        "copay_rounding": copay_rounding,
        "facility_fee_cents": facility_fee_cents,
        "current_utc": clock.EPOCH_ISO,
        "collected_copay_cents": 0,
        "active_queue_count": 0,
    }
    with db.LOCK:
        db.clinics[clinic["id"]] = clinic
    return success(serialize.clinic(clinic), status=201)


@bp.route("/clinics/<cid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_clinic_route(cid):
    clinic = get_clinic(cid)
    return success(serialize.clinic(clinic), status=200)


@bp.route("/clinics", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_clinics():
    records = list(db.clinics.values())
    items, limit, offset, total = paginate(records, serialize.clinic)
    return success_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Provider (PRD §3.1)
# --------------------------------------------------------------------------
@bp.route("/providers", methods=["POST"])
@require_roles("ClinicAdmin")
def create_provider():
    body = request.get_json(silent=True) or {}
    clinic_id = require_string(body, "clinic_id")
    full_name = require_string(body, "full_name")
    get_clinic(clinic_id)

    cleanup_buffer_minutes = opt_int(body, "cleanup_buffer_minutes", 0)
    if cleanup_buffer_minutes < 0:
        raise err(ERR_INVALID_REQUEST, "cleanup_buffer_minutes must be non-negative")

    required_consent_codes = body.get("required_consent_codes")
    if required_consent_codes is None:
        required_consent_codes = []
    if not isinstance(required_consent_codes, list) or \
            not all(isinstance(x, str) for x in required_consent_codes):
        raise err(ERR_INVALID_REQUEST, "required_consent_codes must be a string array")

    questionnaire_required_sections = body.get("questionnaire_required_sections")
    if questionnaire_required_sections is None:
        questionnaire_required_sections = []
    if not isinstance(questionnaire_required_sections, list) or \
            not all(isinstance(x, str) for x in questionnaire_required_sections):
        raise err(ERR_INVALID_REQUEST, "questionnaire_required_sections must be a string array")

    now = db.now_iso()
    provider = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "clinic_id": clinic_id,
        "full_name": full_name,
        "cleanup_buffer_minutes": cleanup_buffer_minutes,
        "required_consent_codes": required_consent_codes,
        "questionnaire_required_sections": questionnaire_required_sections,
    }
    with db.LOCK:
        db.providers[provider["id"]] = provider
    return success(serialize.provider(provider), status=201)


@bp.route("/providers/<pid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_provider_route(pid):
    provider = get_provider(pid)
    return success(serialize.provider(provider), status=200)


@bp.route("/providers", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_providers():
    clinic_id = request.args.get("clinic_id")
    records = list(db.providers.values())
    if clinic_id is not None:
        records = [r for r in records if r["clinic_id"] == clinic_id]
    items, limit, offset, total = paginate(records, serialize.provider)
    return success_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# ExamRoom (PRD §3.1)
# --------------------------------------------------------------------------
@bp.route("/exam-rooms", methods=["POST"])
@require_roles("ClinicAdmin")
def create_exam_room():
    body = request.get_json(silent=True) or {}
    clinic_id = require_string(body, "clinic_id")
    label = require_string(body, "label")
    get_clinic(clinic_id)

    now = db.now_iso()
    room = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "clinic_id": clinic_id,
        "label": label,
    }
    with db.LOCK:
        db.exam_rooms[room["id"]] = room
    return success(serialize.exam_room(room), status=201)


@bp.route("/exam-rooms/<rid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_exam_room_route(rid):
    from services.lookups import get_exam_room
    room = get_exam_room(rid)
    return success(serialize.exam_room(room), status=200)


@bp.route("/exam-rooms", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_exam_rooms():
    clinic_id = request.args.get("clinic_id")
    records = list(db.exam_rooms.values())
    if clinic_id is not None:
        records = [r for r in records if r["clinic_id"] == clinic_id]
    items, limit, offset, total = paginate(records, serialize.exam_room)
    return success_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Patient (PRD §3.2)
# --------------------------------------------------------------------------
@bp.route("/patients", methods=["POST"])
@require_roles("ClinicAdmin", "FrontDeskStaff")
def create_patient():
    body = request.get_json(silent=True) or {}
    clinic_id = require_string(body, "clinic_id")
    legal_name = require_string(body, "legal_name")
    date_of_birth = require_string(body, "date_of_birth")
    phone = require_string(body, "phone")
    get_clinic(clinic_id)

    now = db.now_iso()
    patient = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "clinic_id": clinic_id,
        "legal_name": legal_name,
        "date_of_birth": date_of_birth,
        "phone": phone,
        "demographics_revision": 1,
    }
    with db.LOCK:
        db.patients[patient["id"]] = patient
    return success(serialize.patient(patient), status=201)


@bp.route("/patients/<pid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_patient_route(pid):
    patient = get_patient(pid)
    return success(serialize.patient(patient), status=200)


@bp.route("/patients", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_patients():
    clinic_id = request.args.get("clinic_id")
    records = list(db.patients.values())
    if clinic_id is not None:
        records = [r for r in records if r["clinic_id"] == clinic_id]
    items, limit, offset, total = paginate(records, serialize.patient)
    return success_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Appointment (PRD §3.2)
# --------------------------------------------------------------------------
@bp.route("/appointments", methods=["POST"])
@require_roles("ClinicAdmin", "FrontDeskStaff")
def create_appointment():
    body = request.get_json(silent=True) or {}
    clinic_id = require_string(body, "clinic_id")
    provider_id = require_string(body, "provider_id")
    patient_id = require_string(body, "patient_id")
    start_raw = require_string(body, "start_utc")
    end_raw = require_string(body, "end_utc")
    plan_default_copay_cents = opt_int(body, "plan_default_copay_cents", 0)
    if plan_default_copay_cents < 0:
        raise err(ERR_INVALID_REQUEST, "plan_default_copay_cents must be non-negative")

    # FK existence (PRD §2.5): validate each FK type.
    get_clinic(clinic_id)
    provider = get_provider(provider_id)
    get_patient(patient_id)

    start_utc = clock.parse_instant(start_raw)
    end_utc = clock.parse_instant(end_raw)
    if not (end_utc > start_utc):
        raise err(ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")

    # Provider double-booking check (PRD §3.2): half-open [start, end+buffer).
    buffer_min = provider["cleanup_buffer_minutes"]
    busy = []
    for a in db.appointments.values():
        if a["provider_id"] != provider_id or a["status"] == "CANCELLED":
            continue
        a_start = clock.parse_instant(a["start_utc"])
        a_end = clock.add_hours(clock.parse_instant(a["end_utc"]), buffer_min / 60.0)
        busy.append((a_start, a_end))
    if calculations.provider_overlap(start_utc, end_utc, busy):
        raise err(ERR_PROVIDER_DOUBLE_BOOKED, "provider double-booked")

    provisional = calculations.estimate_copay(plan_default_copay_cents)

    now = db.now_iso()
    appt = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "clinic_id": clinic_id,
        "provider_id": provider_id,
        "patient_id": patient_id,
        "start_utc": clock.format_instant(start_utc),
        "end_utc": clock.format_instant(end_utc),
        "plan_default_copay_cents": plan_default_copay_cents,
        "provisional_copay_cents": provisional,
        "status": "SCHEDULED",
    }
    with db.LOCK:
        db.appointments[appt["id"]] = appt
    return success(serialize.appointment(appt), status=201)


@bp.route("/appointments/<aid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_appointment_route(aid):
    from services.lookups import get_appointment
    appt = get_appointment(aid)
    return success(serialize.appointment(appt), status=200)


@bp.route("/appointments", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_appointments():
    records = list(db.appointments.values())
    for f in ("clinic_id", "provider_id", "patient_id"):
        val = request.args.get(f)
        if val is not None:
            records = [r for r in records if r[f] == val]
    items, limit, offset, total = paginate(records, serialize.appointment)
    return success_list(items, limit, offset, total)
