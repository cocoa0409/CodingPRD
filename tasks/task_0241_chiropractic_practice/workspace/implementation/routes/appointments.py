"""Appointment booking, series materialization, visit-day, and billing flows."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, authorize, get_json_body, paginate
from models import new_record, touch, serialize, serialize_list, clock_now, _parse_iso
from lookups import get_patient_or_404, leaf_or_404, ref_or_404
from response import ok, created
from services.calculations import (
    patient_responsibility, no_show_fee, DISMISSAL_STRIKE_THRESHOLD,
    LATE_CANCEL_WINDOW_HOURS,
)
from services.ledger import add_entry
from services.plans import on_visit_attended, dismiss_patient, cancel_release_appointment
from services.scheduling import (
    check_resources, check_room_type, check_provider_conflict,
    check_room_conflict, reserve_cap,
)
from services.series import generate_series_internal
import validators as V

bp = Blueprint("appointments", __name__)

VISIT_TYPES = {"ADJUSTMENT", "EXAM", "RE_EXAM", "X_RAY", "THERAPY"}
READ_APPT = ["FrontDesk", "Provider", "PracticeAdmin", "BillingClerk"]


def _guard_not_dismissed(patient):
    if patient["status"] == "DISMISSED" or patient.get("is_dismissed"):
        raise err("ERR_PATIENT_DISMISSED", "Patient is dismissed")


# ---- Series materialization ----
@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/series", methods=["POST"])
def create_series(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "Provider"])
    patient = get_patient_or_404(patient_id)
    plan = leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    body = get_json_body()

    plan_phase_id = V.require_str(body, "plan_phase_id")
    provider_id = V.require_str(body, "provider_id")
    treatment_room_id = V.require_str(body, "treatment_room_id")
    start_date = V.require_str(body, "start_date")
    weekday_pattern = body.get("weekday_pattern")
    start_time_minutes = V.require_int(body, "start_time_minutes")
    duration_minutes = V.require_int(body, "duration_minutes")
    insurance_policy_id = body.get("insurance_policy_id")

    # Body FK existence (priority 5).
    phase = ref_or_404(db.plan_phases, plan_phase_id)
    if phase["treatment_plan_id"] != plan_id:
        raise err("ERR_REFERENCE_NOT_FOUND", "Phase does not belong to this plan")
    provider = ref_or_404(db.providers, provider_id)
    room = ref_or_404(db.treatment_rooms, treatment_room_id)
    if insurance_policy_id is not None:
        ref_or_404(db.insurance_policies, insurance_policy_id)

    # Well-formedness (priority 6).
    if weekday_pattern is None or not isinstance(weekday_pattern, list):
        raise err("ERR_INVALID_REQUEST", "weekday_pattern must be an array")
    if start_time_minutes < 0 or start_time_minutes >= 1440:
        raise err("ERR_INVALID_REQUEST", "start_time_minutes must be in [0, 1440)")
    if duration_minutes < 1 or duration_minutes > 240:
        raise err("ERR_INVALID_REQUEST", "duration_minutes must be in [1, 240]")

    # Dismissed guard (priority 9).
    _guard_not_dismissed(patient)

    # Semantic validation (priority 22): weekday_pattern non-empty, entries 0..6.
    if len(weekday_pattern) == 0:
        raise err("ERR_VALIDATION", "weekday_pattern must be non-empty")
    for wd in weekday_pattern:
        if isinstance(wd, bool) or not isinstance(wd, int) or wd < 0 or wd > 6:
            raise err("ERR_VALIDATION", "weekday_pattern entries must be in 0..6")

    # Resource availability (priority 11) + room type (priority 12).
    check_resources(provider, room)
    # Series-generated visits are ADJUSTMENT; X_RAY constraint not triggered, but
    # apply uniformly for safety.
    check_room_type("ADJUSTMENT", room)

    # INSURANCE policy requirement (priority 15).
    if patient["payer_mode"] == "INSURANCE":
        if not insurance_policy_id:
            raise err("ERR_POLICY_REQUIRED", "INSURANCE patient requires an ACTIVE owned policy")
        policy = db.insurance_policies.get(insurance_policy_id)
        if policy is None or policy["patient_id"] != patient_id or policy["status"] != "ACTIVE":
            raise err("ERR_POLICY_REQUIRED", "INSURANCE patient requires an ACTIVE owned policy")

    series = generate_series_internal(
        plan=plan,
        plan_phase=phase,
        provider_id=provider_id,
        treatment_room_id=treatment_room_id,
        start_date=start_date,
        weekday_pattern=weekday_pattern,
        start_time_minutes=start_time_minutes,
        duration_minutes=duration_minutes,
        insurance_policy_id=insurance_policy_id,
    )
    return created(serialize(series))


@bp.route("/patients/<patient_id>/treatment-plans/<plan_id>/series", methods=["GET"])
def list_series(patient_id, plan_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "Provider", "PracticeAdmin"])
    get_patient_or_404(patient_id)
    leaf_or_404(db.treatment_plans, plan_id, patient_id, "patient_id")
    items = [s for s in db.appointment_series.values() if s["treatment_plan_id"] == plan_id]
    plan_phase_id = request.args.get("plan_phase_id")
    status = request.args.get("status")
    if plan_phase_id is not None:
        items = [s for s in items if s["plan_phase_id"] == plan_phase_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


# ---- Single appointment booking ----
@bp.route("/patients/<patient_id>/appointments", methods=["POST"])
def book_appointment(patient_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk", "Provider"])
    patient = get_patient_or_404(patient_id)
    body = get_json_body()

    provider_id = V.require_str(body, "provider_id")
    treatment_room_id = V.require_str(body, "treatment_room_id")
    visit_type = V.require_enum(body, "visit_type", VISIT_TYPES)
    scheduled_start = V.require_str(body, "scheduled_start")
    duration_minutes = V.require_int(body, "duration_minutes")
    plan_phase_id = body.get("plan_phase_id")
    insurance_policy_id = body.get("insurance_policy_id")
    appointment_series_id = body.get("appointment_series_id")
    replaces_appointment_id = body.get("replaces_appointment_id")

    # Body FK existence (priority 5).
    provider = ref_or_404(db.providers, provider_id)
    room = ref_or_404(db.treatment_rooms, treatment_room_id)
    if plan_phase_id is not None:
        ref_or_404(db.plan_phases, plan_phase_id)
    if insurance_policy_id is not None:
        ref_or_404(db.insurance_policies, insurance_policy_id)
    if appointment_series_id is not None:
        ref_or_404(db.appointment_series, appointment_series_id)
    if replaces_appointment_id is not None:
        ref_or_404(db.appointments, replaces_appointment_id)

    # Well-formedness (priority 6).
    if duration_minutes < 1 or duration_minutes > 240:
        raise err("ERR_INVALID_REQUEST", "duration_minutes must be in [1, 240]")
    try:
        start_dt = _parse_iso(scheduled_start)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "scheduled_start must be an ISO 8601 instant")
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Dismissed guard (priority 9).
    _guard_not_dismissed(patient)

    # Resource availability (priority 11).
    check_resources(provider, room)
    # Room type (priority 12).
    check_room_type(visit_type, room)
    # Provider conflict (priority 13).
    check_provider_conflict(provider_id, start_dt, end_dt)
    # Room buffer (priority 14).
    check_room_conflict(room, start_dt, end_dt)

    # INSURANCE policy requirement (priority 15).
    policy = None
    if patient["payer_mode"] == "INSURANCE":
        if not insurance_policy_id:
            raise err("ERR_POLICY_REQUIRED", "INSURANCE patient requires an ACTIVE owned policy")
        policy = db.insurance_policies.get(insurance_policy_id)
        if policy is None or policy["patient_id"] != patient_id or policy["status"] != "ACTIVE":
            raise err("ERR_POLICY_REQUIRED", "INSURANCE patient requires an ACTIVE owned policy")

    # Cap reservation (priority 16) — mutates policy.visits_reserved.
    counts_against_cap = reserve_cap(patient, visit_type, policy) if policy else False

    end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end_dt.microsecond // 1000:03d}Z"
    rec = new_record({
        "patient_id": patient["id"],
        "appointment_series_id": appointment_series_id,
        "plan_phase_id": plan_phase_id,
        "provider_id": provider_id,
        "treatment_room_id": treatment_room_id,
        "insurance_policy_id": insurance_policy_id,
        "visit_type": visit_type,
        "replaces_appointment_id": replaces_appointment_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": end_iso,
        "duration_minutes": duration_minutes,
        "counts_against_cap": counts_against_cap,
        "patient_responsibility_cents": 0,
        "insurance_paid_cents": 0,
        "no_show_fee_cents": 0,
        "attendance_status": "BOOKED",
        "billing_status": "UNBILLED",
    })
    db.appointments[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients/<patient_id>/appointments", methods=["GET"])
def list_appointments(patient_id):
    _, role = authenticate()
    authorize(role, READ_APPT)
    get_patient_or_404(patient_id)
    items = [a for a in db.appointments.values() if a["patient_id"] == patient_id]
    items = _apply_appt_filters(items, request.args, include_patient=False)
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>/appointments/<appt_id>", methods=["GET"])
def get_appointment(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, READ_APPT)
    get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    return ok(serialize(appt))


def _apply_appt_filters(items, args, include_patient):
    if include_patient and args.get("patient_id") is not None:
        items = [a for a in items if a["patient_id"] == args.get("patient_id")]
    for f in ("provider_id", "treatment_room_id", "insurance_policy_id",
              "appointment_series_id", "plan_phase_id", "replaces_appointment_id",
              "attendance_status", "billing_status"):
        v = args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    return items


# ---- Check-in ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/check-in", methods=["POST"])
def check_in(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk"])
    patient = get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    if appt["attendance_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Appointment is not BOOKED")
    if patient["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Patient is not ACTIVE")
    provider = db.providers.get(appt["provider_id"])
    if provider is None or provider["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Assigned provider is not ACTIVE")
    appt["attendance_status"] = "CHECKED_IN"
    touch(appt)
    return ok(serialize(appt))


# ---- SOAP notes ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/soap-note", methods=["POST"])
def create_soap(patient_id, appt_id):
    uid, role = authenticate()
    authorize(role, ["Provider"])
    get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    body = get_json_body()
    provider_id = V.require_str(body, "provider_id")
    ref_or_404(db.providers, provider_id)
    subjective = V.require_str(body, "subjective")
    objective = V.require_str(body, "objective")
    assessment = V.require_str(body, "assessment")
    plan_text = V.require_str(body, "plan")
    # SOAP provider must match appointment provider (priority 20).
    if provider_id != appt["provider_id"]:
        raise err("ERR_SOAP_PROVIDER_MISMATCH", "SOAP note author must match the appointment provider")
    rec = new_record({
        "appointment_id": appt["id"],
        "provider_id": provider_id,
        "subjective": subjective,
        "objective": objective,
        "assessment": assessment,
        "plan": plan_text,
        "status": "DRAFT",
    })
    db.soap_notes[rec["id"]] = rec
    return created(serialize(rec))


@bp.route("/patients/<patient_id>/appointments/<appt_id>/soap-note", methods=["GET"])
def list_soap(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["Provider", "FrontDesk", "PracticeAdmin", "BillingClerk"])
    get_patient_or_404(patient_id)
    leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    items = [s for s in db.soap_notes.values() if s["appointment_id"] == appt_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    window, pg = paginate(items)
    return ok(serialize_list(window), pagination=pg)


@bp.route("/patients/<patient_id>/appointments/<appt_id>/soap-note/sign", methods=["POST"])
def sign_soap(patient_id, appt_id):
    uid, role = authenticate()
    authorize(role, ["Provider"])
    get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    notes = [s for s in db.soap_notes.values() if s["appointment_id"] == appt_id]
    if not notes:
        raise err("ERR_RESOURCE_NOT_FOUND", "SOAP note not found")
    note = notes[0]
    if note["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "SOAP note is not DRAFT")
    if note["provider_id"] != uid or note["provider_id"] != appt["provider_id"]:
        raise err("ERR_FORBIDDEN_ROLE", "Only the appointment provider may sign this note")
    if appt["attendance_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Appointment must be CHECKED_IN to sign the note")
    note["status"] = "SIGNED"
    touch(note)
    return ok(serialize(note))


# ---- Complete ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/complete", methods=["POST"])
def complete(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["Provider"])
    patient = get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    if appt["attendance_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Appointment is not CHECKED_IN")
    # SIGNED SOAP note required (priority 17).
    signed = [s for s in db.soap_notes.values()
              if s["appointment_id"] == appt_id and s["status"] == "SIGNED"]
    if not signed:
        raise err("ERR_SOAP_NOTE_REQUIRED", "A SIGNED SOAP note is required to complete")

    appt["attendance_status"] = "ATTENDED"
    # Cap slot reserved -> committed.
    if appt.get("counts_against_cap"):
        policy = db.insurance_policies.get(appt.get("insurance_policy_id"))
        if policy:
            policy["visits_reserved"] = max(0, policy["visits_reserved"] - 1)
            policy["visits_committed"] += 1
            touch(policy)

    # Compute responsibility (after marking ATTENDED so wellness ordinal counts it).
    pr, ins_paid, applied_ded = patient_responsibility(patient, appt)
    appt["patient_responsibility_cents"] = pr
    appt["insurance_paid_cents"] = ins_paid
    appt["_applied_to_deductible_cents"] = applied_ded
    appt["billing_status"] = "POSTED"
    touch(appt)

    add_entry(patient, "CHARGE", pr, appointment_id=appt["id"], memo="Visit charge")

    # Phase/plan counter bumps + bubble-up.
    on_visit_attended(appt)
    return ok(serialize(appt))


# ---- Cancel ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/cancel", methods=["POST"])
def cancel(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk"])
    patient = get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    if appt["attendance_status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Appointment is not BOOKED")
    now = clock_now()
    start = _parse_iso(appt["scheduled_start"])
    window = timedelta(hours=LATE_CANCEL_WINDOW_HOURS)

    if now < start - window:
        # Clean cancellation.
        appt["attendance_status"] = "CANCELLED"
        if appt.get("counts_against_cap"):
            policy = db.insurance_policies.get(appt.get("insurance_policy_id"))
            if policy:
                policy["visits_reserved"] = max(0, policy["visits_reserved"] - 1)
                touch(policy)
        touch(appt)
        return ok(serialize(appt))

    # Late cancel (within window, still before start).
    appt["attendance_status"] = "LATE_CANCEL"
    if appt.get("counts_against_cap"):
        policy = db.insurance_policies.get(appt.get("insurance_policy_id"))
        if policy:
            policy["visits_reserved"] = max(0, policy["visits_reserved"] - 1)
            touch(policy)
    _record_strike_and_fee(patient, appt, "LATE_CANCEL")
    return ok(serialize(appt))


# ---- No-show ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/no-show", methods=["POST"])
def no_show(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["FrontDesk"])
    patient = get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    now = clock_now()
    status = appt["attendance_status"]
    if status == "BOOKED":
        start = _parse_iso(appt["scheduled_start"])
        if now < start:
            raise err("ERR_INVALID_STATE", "Cannot mark no-show before scheduled_start")
    elif status == "CHECKED_IN":
        end = _parse_iso(appt["scheduled_end"])
        if now < end:
            raise err("ERR_INVALID_STATE", "Cannot mark no-show before scheduled_end")
    else:
        raise err("ERR_INVALID_STATE", "Appointment cannot transition to NO_SHOW")

    appt["attendance_status"] = "NO_SHOW"
    if appt.get("counts_against_cap"):
        policy = db.insurance_policies.get(appt.get("insurance_policy_id"))
        if policy:
            policy["visits_reserved"] = max(0, policy["visits_reserved"] - 1)
            touch(policy)
    _record_strike_and_fee(patient, appt, "NO_SHOW")
    return ok(serialize(appt))


def _record_strike_and_fee(patient, appt, transition):
    patient["no_show_strike_count"] += 1
    touch(patient)
    fee = no_show_fee(patient["no_show_strike_count"], transition)
    appt["no_show_fee_cents"] = fee
    appt["billing_status"] = "POSTED"
    touch(appt)
    add_entry(patient, "NO_SHOW_FEE", fee, appointment_id=appt["id"], memo="No-show fee")
    if patient["no_show_strike_count"] >= DISMISSAL_STRIKE_THRESHOLD and patient["status"] == "ACTIVE":
        dismiss_patient(patient)


# ---- Adjudicate ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/adjudicate", methods=["POST"])
def adjudicate(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["BillingClerk"])
    patient = get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    if appt["billing_status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Appointment is not POSTED")
    if appt["attendance_status"] != "ATTENDED":
        raise err("ERR_INVALID_STATE", "Appointment is not ATTENDED")
    if patient["payer_mode"] != "INSURANCE":
        raise err("ERR_INVALID_STATE", "Patient is not INSURANCE")
    if not appt.get("insurance_policy_id"):
        raise err("ERR_INVALID_STATE", "Appointment has no insurance policy")

    appt["billing_status"] = "ADJUDICATED"
    touch(appt)
    add_entry(patient, "INSURANCE_PAYMENT", -appt["insurance_paid_cents"],
              appointment_id=appt["id"], memo="Insurance payment")
    policy = db.insurance_policies.get(appt["insurance_policy_id"])
    applied = appt.get("_applied_to_deductible_cents", 0)
    if policy and applied:
        policy["deductible_met_cents"] += applied
        touch(policy)
    return ok(serialize(appt))


# ---- Write-off ----
@bp.route("/patients/<patient_id>/appointments/<appt_id>/write-off", methods=["POST"])
def write_off(patient_id, appt_id):
    _, role = authenticate()
    authorize(role, ["BillingClerk"])
    patient = get_patient_or_404(patient_id)
    appt = leaf_or_404(db.appointments, appt_id, patient_id, "patient_id")
    if appt["billing_status"] != "POSTED":
        raise err("ERR_INVALID_STATE", "Appointment is not POSTED")
    appt["billing_status"] = "WRITTEN_OFF"
    touch(appt)
    add_entry(patient, "WRITE_OFF", -appt["patient_responsibility_cents"],
              appointment_id=appt["id"], memo="Charge write-off")
    return ok(serialize(appt))
