"""Utilization, chair billing, the daily checkpoint and the test-driving hooks."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
from db import apply_changes, get, must, new_row, rows
from middleware import authenticate
from response import created, ok
from services import derive, present
from services.derive import CHAIR_UNIT_CENTS, UTILISATION_STATUSES
from validators import (
    body,
    opt_bool,
    opt_enum,
    opt_int,
    q_date,
    q_enum,
    req_date,
    req_enum,
    req_instant,
    req_int,
    req_str,
)

bp = Blueprint("reports", __name__)

VARIANTS = ("SCHEDULED", "ACTUAL")
LIVE_STATUSES = ("INFUSING", "OBSERVING")
DOSED_STATUSES = ("INFUSING", "OBSERVING", "COMPLETED")
TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "NO_SHOW")
BOOKING_CLASSES = ("ROUTINE", "SAME_DAY_ADDON", "URGENT")


def _day_visits(center_id, service_date):
    return [
        appointment
        for appointment in rows("appointments")
        if appointment.get("center_id") == center_id
        and appointment.get("service_date") == service_date
    ]


def _biosimilar_savings(visits):
    total = 0
    for appointment in visits:
        if appointment["schedule_status"] not in DOSED_STATUSES:
            continue
        drug = derive.drug_of_appointment(appointment)
        if drug is None or drug.get("is_biosimilar"):
            continue
        reference_cost = int(drug.get("unit_cost_cents") or 0)
        candidates = [
            other
            for other in rows("drugs")
            if other.get("reference_drug_id") == drug["id"]
            and other.get("is_biosimilar")
            and int(other.get("unit_cost_cents") or 0) < reference_cost
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda d: (int(d.get("unit_cost_cents") or 0), d["_seq"]))
        alternative = candidates[0]
        units = 0
        for prep in derive.preps_of(appointment["id"]):
            if prep["status"] in ("PREPARED", "ADMINISTERED"):
                units += int(prep.get("units_requested") or 0)
        total += units * (reference_cost - int(alternative.get("unit_cost_cents") or 0))
    return total


@bp.get("/infusion-centers/<center_id>/utilization")
def utilization(center_id):
    authenticate("Scheduler", "MedicalDirector")
    service_date = q_date("service_date", required=True)
    variant = q_enum("variant", VARIANTS, "SCHEDULED")
    center = must("centers", center_id)
    open_span = int(center["close_minute"]) - int(center["open_minute"])
    available_chairs = sum(
        1 for chair in derive.chairs_of_center(center_id) if chair["status"] == "AVAILABLE"
    )
    available_minutes = available_chairs * open_span

    visits = _day_visits(center_id, service_date)
    occupied = 0
    counted = 0
    if variant == "SCHEDULED":
        for appointment in visits:
            if appointment["schedule_status"] in UTILISATION_STATUSES:
                occupied += int(appointment.get("chair_minutes") or 0)
                counted += 1
    else:
        clock_minute = db.clock_minute_of_day()
        for appointment in visits:
            status = appointment["schedule_status"]
            start = appointment.get("actual_start_minute")
            if status == "COMPLETED":
                end = appointment.get("actual_end_minute")
                if start is not None and end is not None:
                    occupied += int(end) - int(start)
                counted += 1
            elif status in LIVE_STATUSES:
                if start is not None:
                    occupied += clock_minute - int(start)
                counted += 1

    if available_minutes == 0:
        pct = Decimal("0.00")
    else:
        pct = db.rhu(Decimal(occupied) / Decimal(available_minutes) * Decimal(100), 2)
    return ok(
        {
            "center_id": center_id,
            "service_date": service_date,
            "variant": variant,
            "available_chair_minutes": available_minutes,
            "occupied_chair_minutes": occupied,
            "utilization_pct": float(pct),
            "appointment_count": counted,
            "biosimilar_savings_cents": _biosimilar_savings(visits),
        }
    )


@bp.get("/infusion-centers/<center_id>/chair-billing-summary")
def chair_billing_summary(center_id):
    authenticate("Scheduler", "MedicalDirector")
    service_date = q_date("service_date", required=True)
    must("centers", center_id)
    units = 0
    count = 0
    for appointment in _day_visits(center_id, service_date):
        if appointment["schedule_status"] != "COMPLETED":
            continue
        count += 1
        units += int(appointment.get("billable_chair_units") or 0)
    return ok(
        {
            "center_id": center_id,
            "service_date": service_date,
            "completed_appointment_count": count,
            "day_billable_units": units,
            "day_billable_cents": units * CHAIR_UNIT_CENTS,
        }
    )


@bp.post("/infusion-centers/<center_id>/daily-sweep")
def daily_sweep(center_id):
    authenticate("Scheduler")
    data = body()
    service_date = req_date(data, "service_date")
    must("centers", center_id)
    now = db.now()

    # Step 1 — expire drug lots (global scope, created_at ascending).
    expired_lots = 0
    for lot in rows("lots"):
        if lot["status"] not in ("AVAILABLE", "DEPLETED"):
            continue
        expires = lot.get("_expires_dt")
        if expires is not None and expires <= now:
            apply_changes(lot, {"status": "EXPIRED"})
            expired_lots += 1

    # Step 2 — expire approved authorizations and re-derive their visits.
    expired_auths = 0
    for auth in rows("auths"):
        if auth["status"] != "APPROVED":
            continue
        expires = auth.get("_expires_dt")
        if expires is not None and expires <= now:
            apply_changes(auth, {"status": "EXPIRED"})
            expired_auths += 1
            appointment = get("appointments", auth["appointment_id"])
            if appointment is not None:
                derive.sync_readiness(appointment)

    # Step 3 — waste prepared doses whose stability window has lapsed.
    wasted = 0
    for prep in rows("preps"):
        if prep["status"] != "PREPARED":
            continue
        usable = prep.get("_usable_dt")
        if usable is not None and usable <= now:
            derive.prep_to_wasted(prep)
            wasted += 1

    # Step 4 — mark no-shows for the named center and service date.
    no_shows = 0
    for appointment in rows("appointments"):
        if appointment.get("center_id") != center_id:
            continue
        if appointment.get("service_date") != service_date:
            continue
        if appointment["schedule_status"] not in ("TENTATIVE", "CONFIRMED"):
            continue
        grace = db.instant_of(service_date, int(appointment.get("start_minute") or 0)) + timedelta(
            minutes=30
        )
        if now < grace:
            continue
        chair_id = appointment.get("chair_id")
        nurse_id = appointment.get("nurse_id")
        derive.release_doses_for_cancellation(appointment)
        apply_changes(appointment, {"schedule_status": "NO_SHOW"})
        derive.recompute_chair(chair_id)
        derive.recompute_nurse(nurse_id)
        derive.recompute_patient(get("patients", appointment.get("patient_id")))
        no_shows += 1

    return ok(
        {
            "center_id": center_id,
            "service_date": service_date,
            "expired_lot_count": expired_lots,
            "expired_authorization_count": expired_auths,
            "wasted_preparation_count": wasted,
            "no_show_count": no_shows,
        }
    )


# ------------------------------------------------------------------ test hooks
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate("Scheduler", "Pharmacist", "InfusionNurse", "AuthorizationSpecialist", "MedicalDirector")
    data = body()
    moment, raw = req_instant(data, "current_utc")
    previous = db.clock_raw()
    db.set_clock(moment, raw)
    return ok({"current_utc": raw, "previous_utc": previous})


@bp.post("/_inject/appointment_history")
def inject_history():
    authenticate("Scheduler")
    data = body()
    center_id = req_str(data, "center_id", 1, None)
    patient_id = req_str(data, "patient_id", 1, None)
    plan_id = req_str(data, "treatment_plan_id", 1, None)
    template_id = req_str(data, "template_id", 1, None)
    service_date = req_date(data, "service_date")
    schedule_status = req_enum(data, "schedule_status", TERMINAL_STATUSES)
    chair_minutes = req_int(data, "chair_minutes", 0, None)
    start_minute = opt_int(data, "start_minute", 0, 1439, 0)
    actual_start = opt_int(data, "actual_start_minute", 0, 1439, None, allow_null=True)
    actual_end = opt_int(data, "actual_end_minute", 0, 1439, None, allow_null=True)
    late_cancellation = opt_bool(data, "late_cancellation", False)
    booking_class = opt_enum(data, "booking_class", BOOKING_CLASSES, "ROUTINE")
    cycle_number = opt_int(data, "cycle_number", 1, None, 1)

    must("centers", center_id)
    patient = must("patients", patient_id)
    plan = must("plans", plan_id)
    template = must("templates", template_id)

    if actual_start is not None and actual_end is not None:
        billable = db.ceil_div(max(int(actual_end) - int(actual_start), 0), 15)
    else:
        billable = 0

    appointment = new_row(
        "appointments",
        {
            "center_id": center_id,
            "patient_id": patient_id,
            "treatment_plan_id": plan_id,
            "template_id": template_id,
            "chair_id": None,
            "nurse_id": None,
            "rescheduled_from_appointment_id": None,
            "service_date": service_date,
            "requested_start_minute": start_minute,
            "cycle_number": cycle_number,
            "booking_class": booking_class,
            "template_version_pinned": template["version"],
            "premed_minutes": 0,
            "admin_minutes": chair_minutes,
            "observation_minutes": 0,
            "chair_minutes": chair_minutes,
            "start_minute": start_minute,
            "end_minute": start_minute + chair_minutes,
            "acuity_points": int(template.get("acuity_points") or 0),
            "observation_extension_minutes": 0,
            "actual_start_minute": actual_start,
            "actual_end_minute": actual_end,
            "billable_chair_units": billable,
            "late_cancellation": late_cancellation,
            "cancellation_charge_cents": 0,
            "reminder_cadence_code": derive.CADENCE_CODES.get(
                patient.get("reminder_tier") or "STANDARD", "C_STANDARD"
            ),
            "schedule_status": schedule_status,
            "readiness_status": "PENDING",
        },
    )
    appointment["readiness_status"] = derive.derive_readiness(appointment)
    derive.recompute_patient(patient)
    if schedule_status == "COMPLETED":
        derive.recompute_plan_cycles(plan)
    return created(present.appointment_out(appointment))
