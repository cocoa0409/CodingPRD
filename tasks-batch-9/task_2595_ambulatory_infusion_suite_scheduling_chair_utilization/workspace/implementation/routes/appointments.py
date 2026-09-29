"""Appointments: booking, the chair-side day, cancellation and reschedule."""

from datetime import timedelta

from flask import Blueprint

import db
from db import apply_changes, get, must, new_row, rows
from errors import ApiError
from middleware import authenticate, actor_id, require_nurse_owner, require_patient_owner
from response import created, ok
from routes.common import paged
from services import booking, derive, present
from services.derive import (
    BUMPABLE_STATUSES,
    CADENCE_CODES,
    COMMITTED_STATUSES,
    GRADE_EXTENSION,
    REMINDER_CAPS,
    TERMINAL_STATUSES,
)
from validators import (
    body,
    opt_enum,
    opt_int,
    present as has,
    q_date,
    q_enum,
    q_str,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("appointments", __name__)

ALL_STAFF = ("Scheduler", "InfusionNurse", "Pharmacist", "AuthorizationSpecialist", "MedicalDirector")
BOOKING_CLASSES = ("ROUTINE", "SAME_DAY_ADDON", "URGENT")
SCHEDULE_STATUSES = (
    "TENTATIVE",
    "CONFIRMED",
    "CHECKED_IN",
    "INFUSING",
    "OBSERVING",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
)
READINESS_STATUSES = ("PENDING", "AUTH_CLEARED", "LAB_CLEARED", "FULLY_CLEARED", "BLOCKED")
CHANNELS = ("SMS", "VOICE", "PORTAL")
ACTIONS = ("SLOW_RATE", "HOLD", "ABORT")


# ------------------------------------------------------------------ helpers
def check_terminal(appointment):
    if appointment["schedule_status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_APPOINTMENT_TERMINAL")


def check_state(appointment, allowed):
    check_terminal(appointment)
    if appointment["schedule_status"] not in allowed:
        raise ApiError("ERR_INVALID_SCHEDULE_STATE")


def check_plan_bars(plan):
    if plan["status"] == "SUSPENDED":
        raise ApiError("ERR_PLAN_SUSPENDED")
    if plan["status"] == "COMPLETED":
        raise ApiError("ERR_PLAN_COMPLETED")
    if plan["status"] == "SUPERSEDED":
        raise ApiError("ERR_PLAN_SUPERSEDED")


def check_cycle(plan, cycle_number, exclude_id=None):
    if cycle_number < 1 or cycle_number > int(plan["total_cycles"]):
        raise ApiError("ERR_CYCLE_OUT_OF_RANGE")
    for other in derive.appointments_of_plan(plan["id"]):
        if other["id"] == exclude_id:
            continue
        if other["schedule_status"] in COMMITTED_STATUSES or other["schedule_status"] == "COMPLETED":
            if int(other.get("cycle_number") or 0) == cycle_number:
                raise ApiError("ERR_CYCLE_OUT_OF_RANGE")


def check_open_reaction_for_booking(patient_id, drug_id):
    for event in rows("events"):
        if event["status"] not in ("REPORTED", "UNDER_REVIEW"):
            continue
        appointment = get("appointments", event["appointment_id"])
        if appointment is None or appointment.get("patient_id") != patient_id:
            continue
        plan = derive.plan_of(appointment)
        if plan is not None and plan.get("drug_id") == drug_id:
            raise ApiError("ERR_ADVERSE_EVENT_OPEN")


def check_double_booking(patient_id, service_date, start, chair_minutes, exclude_id=None):
    end = start + chair_minutes
    for other in rows("appointments"):
        if other["id"] == exclude_id:
            continue
        if other.get("patient_id") != patient_id:
            continue
        if other.get("service_date") != service_date:
            continue
        if other["schedule_status"] in TERMINAL_STATUSES:
            continue
        other_start = int(other.get("start_minute") or 0)
        other_end = int(other.get("end_minute") or 0)
        if start < other_end and other_start < end:
            raise ApiError("ERR_PATIENT_DOUBLE_BOOKED")


def check_temporal(center, service_date, booking_class, addon_rules=True):
    today = db.clock_date().isoformat()
    if service_date < today:
        raise ApiError("ERR_SERVICE_DATE_IN_PAST")
    if not addon_rules:
        return
    if service_date == today and booking_class == "ROUTINE":
        raise ApiError("ERR_SAME_DAY_REQUIRES_ADDON")
    if booking_class in ("SAME_DAY_ADDON", "URGENT") and service_date != today:
        raise ApiError("ERR_ADDON_DATE_MISMATCH")
    if booking_class == "SAME_DAY_ADDON":
        if db.clock_minute_of_day() > int(center["addon_cutoff_minute"]):
            raise ApiError("ERR_ADDON_CUTOFF_PASSED")


def cadence_code_for(patient):
    return CADENCE_CODES.get((patient or {}).get("reminder_tier") or "STANDARD", "C_STANDARD")


# ------------------------------------------------------------------ booking
@bp.post("/appointments")
def create_appointment():
    authenticate("Scheduler")
    data = body()
    center_id = req_str(data, "center_id", 1, None)
    patient_id = req_str(data, "patient_id", 1, None)
    plan_id = req_str(data, "treatment_plan_id", 1, None)
    template_id = req_str(data, "template_id", 1, None)
    service_date = req_date(data, "service_date")
    requested_start_minute = req_int(data, "requested_start_minute", 0, 1439)
    cycle_number = req_int(data, "cycle_number", None, None)
    booking_class = opt_enum(data, "booking_class", BOOKING_CLASSES, "ROUTINE")
    template_version = opt_int(data, "template_version", None, None)

    center = must("centers", center_id)
    patient = must("patients", patient_id)
    plan = must("plans", plan_id)
    template = must("templates", template_id)

    check_plan_bars(plan)
    if template["status"] == "RETIRED":
        raise ApiError("ERR_TEMPLATE_RETIRED")

    if plan["patient_id"] != patient_id:
        raise ApiError("ERR_PLAN_PATIENT_MISMATCH")
    if template["drug_id"] != plan["drug_id"]:
        raise ApiError("ERR_TEMPLATE_DRUG_MISMATCH")
    if template["center_id"] != center_id:
        raise ApiError("ERR_TEMPLATE_CENTER_MISMATCH")
    window = booking.build_window(plan, patient, template)
    if template_version is not None and template_version != template["version"]:
        raise ApiError("ERR_TEMPLATE_VERSION_STALE")
    check_cycle(plan, cycle_number)

    check_open_reaction_for_booking(patient_id, plan["drug_id"])
    if patient["steering_status"] != "SUITE":
        raise ApiError("ERR_PATIENT_STEERING_HOLD")

    check_temporal(center, service_date, booking_class)
    snapped = booking.check_operating_hours(center, requested_start_minute, window["chair_minutes"])
    check_double_booking(patient_id, service_date, snapped, window["chair_minutes"])

    if booking_class == "URGENT":
        booking.check_urgent_reserve_limit(center_id, service_date)
    start, chair, nurse = booking.select_slot(
        center,
        service_date,
        window["chair_minutes"],
        window["acuity_points"],
        booking_class,
        snapped,
    )

    appointment = new_row(
        "appointments",
        {
            "center_id": center_id,
            "patient_id": patient_id,
            "treatment_plan_id": plan_id,
            "template_id": template_id,
            "chair_id": chair["id"],
            "nurse_id": nurse["id"],
            "rescheduled_from_appointment_id": None,
            "service_date": service_date,
            "requested_start_minute": requested_start_minute,
            "cycle_number": cycle_number,
            "booking_class": booking_class,
            "template_version_pinned": template["version"],
            "premed_minutes": window["premed_minutes"],
            "admin_minutes": window["admin_minutes"],
            "observation_minutes": window["observation_minutes"],
            "chair_minutes": window["chair_minutes"],
            "start_minute": start,
            "end_minute": start + window["chair_minutes"],
            "acuity_points": window["acuity_points"],
            "observation_extension_minutes": 0,
            "actual_start_minute": None,
            "actual_end_minute": None,
            "billable_chair_units": 0,
            "late_cancellation": False,
            "cancellation_charge_cents": 0,
            "reminder_cadence_code": cadence_code_for(patient),
            "schedule_status": "TENTATIVE",
            "readiness_status": "PENDING",
        },
    )
    appointment["readiness_status"] = derive.derive_readiness(appointment)
    derive.recompute_chair(chair["id"])
    derive.recompute_nurse(nurse["id"])
    return created(present.appointment_out(appointment))


@bp.get("/appointments/<appointment_id>")
def read_appointment(appointment_id):
    authenticate(*(ALL_STAFF + ("Patient",)))
    appointment = get("appointments", appointment_id)
    if appointment is not None:
        require_patient_owner(appointment["patient_id"])
    return ok(present.appointment_out(must("appointments", appointment_id)))


@bp.get("/appointments")
def list_appointments():
    authenticate(*ALL_STAFF)
    filters = {
        "center_id": q_str("center_id"),
        "patient_id": q_str("patient_id"),
        "treatment_plan_id": q_str("treatment_plan_id"),
        "template_id": q_str("template_id"),
        "chair_id": q_str("chair_id"),
        "nurse_id": q_str("nurse_id"),
        "rescheduled_from_appointment_id": q_str("rescheduled_from_appointment_id"),
    }
    service_date = q_date("service_date")
    schedule_status = q_enum("schedule_status", SCHEDULE_STATUSES)
    readiness_status = q_enum("readiness_status", READINESS_STATUSES)
    booking_class = q_enum("booking_class", BOOKING_CLASSES)
    items = []
    for appointment in rows("appointments"):
        if any(value is not None and appointment.get(key) != value for key, value in filters.items()):
            continue
        if service_date is not None and appointment["service_date"] != service_date:
            continue
        if schedule_status is not None and appointment["schedule_status"] != schedule_status:
            continue
        if readiness_status is not None and derive.derive_readiness(appointment) != readiness_status:
            continue
        if booking_class is not None and appointment["booking_class"] != booking_class:
            continue
        items.append(appointment)
    items.sort(key=lambda a: (a["service_date"], int(a.get("start_minute") or 0), a["_seq"]))
    return paged("appointments", items)


# ------------------------------------------------------------------ lifecycle
@bp.post("/appointments/<appointment_id>/confirm")
def confirm_appointment(appointment_id):
    authenticate("Scheduler")
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("TENTATIVE",))
    if appointment.get("chair_id") is None or appointment.get("nurse_id") is None:
        raise ApiError("ERR_INVALID_SCHEDULE_STATE")
    plan = derive.plan_of(appointment)
    if plan is not None:
        check_plan_bars(plan)
    template = get("templates", appointment["template_id"])
    if template is not None and appointment.get("template_version_pinned") != template["version"]:
        raise ApiError("ERR_TEMPLATE_VERSION_STALE")
    live_auth = False
    for auth in derive.auths_of(appointment_id):
        if auth["status"] == "APPROVED" and auth.get("_expires_dt") is not None:
            if auth["_expires_dt"] > db.now():
                live_auth = True
    if not live_auth:
        raise ApiError("ERR_AUTH_NOT_APPROVED")
    apply_changes(
        appointment,
        {
            "schedule_status": "CONFIRMED",
            "readiness_status": derive.derive_readiness(appointment),
        },
    )
    return ok(present.appointment_out(appointment))


@bp.post("/appointments/<appointment_id>/check-in")
def check_in(appointment_id):
    authenticate("Scheduler", "InfusionNurse")
    appointment = get("appointments", appointment_id)
    require_nurse_owner(appointment)
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("CONFIRMED",))
    approved = [a for a in derive.auths_of(appointment_id) if a["status"] == "APPROVED"]
    if not approved:
        raise ApiError("ERR_AUTH_NOT_APPROVED")
    if not any(a.get("_expires_dt") is not None and a["_expires_dt"] > db.now() for a in approved):
        raise ApiError("ERR_AUTH_EXPIRED")
    if db.clock_date().isoformat() != appointment["service_date"]:
        raise ApiError("ERR_CHECK_IN_WRONG_DAY")
    apply_changes(appointment, {"schedule_status": "CHECKED_IN"})
    return ok(present.appointment_out(appointment))


@bp.post("/appointments/<appointment_id>/start-infusion")
def start_infusion(appointment_id):
    authenticate("InfusionNurse")
    appointment = get("appointments", appointment_id)
    require_nurse_owner(appointment)
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("CHECKED_IN",))
    if derive.derive_readiness(appointment) == "BLOCKED":
        raise ApiError("ERR_ADVERSE_EVENT_OPEN")
    for event in rows("events"):
        if event["status"] not in ("REPORTED", "UNDER_REVIEW"):
            continue
        other = get("appointments", event["appointment_id"])
        if other is not None and other.get("patient_id") == appointment["patient_id"]:
            raise ApiError("ERR_ADVERSE_EVENT_OPEN")
    drug = derive.drug_of_appointment(appointment)
    failure = derive.lab_gate(appointment["patient_id"], drug, derive.center_of(appointment))
    if failure:
        raise ApiError(failure)
    if not any(p["status"] == "PREPARED" for p in derive.preps_of(appointment_id)):
        raise ApiError("ERR_PREPARATION_NOT_READY")
    apply_changes(
        appointment,
        {
            "schedule_status": "INFUSING",
            "actual_start_minute": db.clock_minute_of_day(),
        },
    )
    return ok(present.appointment_out(appointment))


@bp.post("/appointments/<appointment_id>/complete-infusion")
def complete_infusion(appointment_id):
    authenticate("InfusionNurse")
    appointment = get("appointments", appointment_id)
    require_nurse_owner(appointment)
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("INFUSING",))
    apply_changes(appointment, {"schedule_status": "OBSERVING"})
    return ok(present.appointment_out(appointment))


@bp.post("/appointments/<appointment_id>/discharge")
def discharge(appointment_id):
    authenticate("InfusionNurse")
    appointment = get("appointments", appointment_id)
    require_nurse_owner(appointment)
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("OBSERVING",))
    if derive.has_blocking_event(appointment_id):
        raise ApiError("ERR_ADVERSE_EVENT_OPEN")
    end_minute = db.clock_minute_of_day()
    start_minute = appointment.get("actual_start_minute")
    if start_minute is None:
        billable = 0
    else:
        billable = db.ceil_div(max(end_minute - int(start_minute), 0), 15)
    for prep in derive.preps_of(appointment_id):
        if prep["status"] == "PREPARED":
            derive.prep_to_administered(prep)
    chair_id = appointment.get("chair_id")
    nurse_id = appointment.get("nurse_id")
    apply_changes(
        appointment,
        {
            "schedule_status": "COMPLETED",
            "actual_end_minute": end_minute,
            "billable_chair_units": billable,
        },
    )
    derive.recompute_chair(chair_id)
    derive.recompute_nurse(nurse_id)
    plan = derive.plan_of(appointment)
    if plan is not None:
        derive.recompute_plan_cycles(plan)
        if plan["status"] == "ACTIVE" and int(plan["completed_cycles"]) >= int(plan["total_cycles"]):
            apply_changes(plan, {"status": "COMPLETED"})
    derive.recompute_patient(get("patients", appointment["patient_id"]))
    return ok(present.appointment_out(appointment))


@bp.post("/appointments/<appointment_id>/cancel")
def cancel(appointment_id):
    authenticate("Scheduler", "Patient")
    appointment = get("appointments", appointment_id)
    if appointment is not None:
        require_patient_owner(appointment["patient_id"])
    data = body()
    req = data.get("reason")
    if req is not None and not isinstance(req, str):
        from validators import bad

        bad("Field 'reason' must be a string.")
    appointment = must("appointments", appointment_id)
    check_state(appointment, ("TENTATIVE", "CONFIRMED", "CHECKED_IN"))
    derive.cancel_appointment(appointment, system=False)
    return ok(present.appointment_out(appointment))


@bp.post("/appointments/<appointment_id>/reschedule")
def reschedule(appointment_id):
    authenticate("Scheduler")
    data = body()
    service_date = req_date(data, "service_date")
    requested_start_minute = req_int(data, "requested_start_minute", 0, 1439)
    booking_class = opt_enum(data, "booking_class", BOOKING_CLASSES)
    expected_version = req_int(data, "expected_appointment_version", None, None)
    original = must("appointments", appointment_id)
    if expected_version != original["version"]:
        raise ApiError("ERR_STALE_APPOINTMENT_VERSION")
    check_state(original, ("TENTATIVE", "CONFIRMED"))

    plan = must("plans", original["treatment_plan_id"])
    template = must("templates", original["template_id"])
    center = must("centers", original["center_id"])
    patient = must("patients", original["patient_id"])
    effective_class = booking_class or original["booking_class"]

    check_plan_bars(plan)
    if template["status"] == "RETIRED":
        raise ApiError("ERR_TEMPLATE_RETIRED")
    if template["drug_id"] != plan["drug_id"]:
        raise ApiError("ERR_TEMPLATE_DRUG_MISMATCH")
    if template["center_id"] != original["center_id"]:
        raise ApiError("ERR_TEMPLATE_CENTER_MISMATCH")
    window = booking.build_window(plan, patient, template)
    check_cycle(plan, int(original["cycle_number"]), exclude_id=original["id"])

    check_temporal(center, service_date, effective_class, addon_rules=False)
    snapped = booking.check_operating_hours(center, requested_start_minute, window["chair_minutes"])
    check_double_booking(
        patient["id"], service_date, snapped, window["chair_minutes"], exclude_id=original["id"]
    )
    # The original's chair and nurse are released before the selector runs.
    start, chair, nurse = booking.select_slot(
        center,
        service_date,
        window["chair_minutes"],
        window["acuity_points"],
        effective_class,
        snapped,
        exclude_ids=(original["id"],),
    )

    derive.cancel_appointment(original, system=True)

    replacement = new_row(
        "appointments",
        {
            "center_id": original["center_id"],
            "patient_id": original["patient_id"],
            "treatment_plan_id": original["treatment_plan_id"],
            "template_id": original["template_id"],
            "chair_id": chair["id"],
            "nurse_id": nurse["id"],
            "rescheduled_from_appointment_id": original["id"],
            "service_date": service_date,
            "requested_start_minute": requested_start_minute,
            "cycle_number": original["cycle_number"],
            "booking_class": effective_class,
            "template_version_pinned": template["version"],
            "premed_minutes": window["premed_minutes"],
            "admin_minutes": window["admin_minutes"],
            "observation_minutes": window["observation_minutes"],
            "chair_minutes": window["chair_minutes"],
            "start_minute": start,
            "end_minute": start + window["chair_minutes"],
            "acuity_points": window["acuity_points"],
            "observation_extension_minutes": 0,
            "actual_start_minute": None,
            "actual_end_minute": None,
            "billable_chair_units": 0,
            "late_cancellation": False,
            "cancellation_charge_cents": 0,
            "reminder_cadence_code": cadence_code_for(patient),
            "schedule_status": "TENTATIVE",
            "readiness_status": "PENDING",
        },
    )
    replacement["readiness_status"] = derive.derive_readiness(replacement)
    derive.recompute_chair(chair["id"])
    derive.recompute_nurse(nurse["id"])
    return created(present.appointment_out(replacement))
