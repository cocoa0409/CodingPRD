"""Appointment series materialization (PRD §3.5, scaffold §1.3 series_generation)."""
from datetime import date, datetime, timedelta, timezone

import db
from errors import err
from models import new_record, touch
from services.scheduling import (
    check_resources, check_room_type, check_provider_conflict,
    check_room_conflict, reserve_cap,
)


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _iso_instant(d, minutes):
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _enumerate_dates(start_date, weekday_pattern, count):
    """Walk forward from start_date emitting `count` dates on the weekdays in
    weekday_pattern (0=Mon..6=Sun), week by week, ascending within each week,
    skipping dates earlier than start_date.
    """
    sd = _parse_date(start_date)
    # Monday of the week containing start_date.
    week_start = sd - timedelta(days=sd.weekday())
    pattern = sorted(set(weekday_pattern))
    out = []
    guard = 0
    while len(out) < count:
        guard += 1
        if guard > 100000:
            break
        for wd in pattern:
            d = week_start + timedelta(days=wd)
            if d < sd:
                continue
            out.append(d)
            if len(out) == count:
                break
        week_start += timedelta(days=7)
    return out


def generate_series_internal(plan, plan_phase, provider_id, treatment_room_id,
                             start_date, weekday_pattern, start_time_minutes,
                             duration_minutes, insurance_policy_id):
    """Materialize exactly plan_phase.planned_visit_count appointments atomically.

    All scheduling/cap checks run per generated booking; any failure aborts the
    whole batch (no partial series). Assumes resources/refs already validated by
    the caller for the route path; re-validates conflicts/cap against current state.
    Returns the created AppointmentSeries record.
    """
    patient = db.patients[plan["patient_id"]]
    provider = db.providers[provider_id]
    room = db.treatment_rooms[treatment_room_id]
    policy = db.insurance_policies.get(insurance_policy_id) if insurance_policy_id else None

    count = plan_phase["planned_visit_count"]
    dates = _enumerate_dates(start_date, weekday_pattern, count)

    # Build candidate appointment records first; validate each against existing
    # state AND prior candidates in this batch; only commit on full success.
    staged = []
    pending_provider = []  # (start_dt, end_dt) committed-in-batch for provider
    pending_room = []

    cap_reservations = 0

    for d in dates:
        start_iso = _iso_instant(d, start_time_minutes)
        start_dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=start_time_minutes)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        end_iso = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # Conflicts vs existing BOOKED/CHECKED_IN appts.
        check_provider_conflict(provider_id, start_dt, end_dt)
        check_room_conflict(room, start_dt, end_dt)
        # Conflicts vs other appointments already staged in this batch.
        for (ps, pe) in pending_provider:
            if start_dt < pe and ps < end_dt:
                raise err("ERR_PROVIDER_DOUBLE_BOOKED", "Provider is double-booked within the series")
        buf = timedelta(minutes=room.get("turnover_buffer_minutes", 0) or 0)
        for (rs, re_) in pending_room:
            if start_dt >= re_ + buf:
                continue
            if end_dt + buf <= rs:
                continue
            raise err("ERR_ROOM_BUFFER_CONFLICT", "Room buffer conflict within the series")

        # Cap reservation (atomic across the batch): project including prior
        # in-batch reservations.
        counts_against_cap = False
        if patient["payer_mode"] == "INSURANCE" and policy is not None:
            from services.calculations import CAP_COUNTING_VISIT_TYPES
            if plan_phase_visit_type(plan_phase) in CAP_COUNTING_VISIT_TYPES:
                projected = policy["visits_reserved"] + policy["visits_committed"] + cap_reservations + 1
                if projected > policy["annual_visit_cap"]:
                    raise err("ERR_VISIT_CAP_EXCEEDED", "Insurance visit cap exceeded")
                counts_against_cap = True
                cap_reservations += 1

        staged.append((start_iso, end_iso, start_dt, end_dt, counts_against_cap))
        pending_provider.append((start_dt, end_dt))
        pending_room.append((start_dt, end_dt))

    # All checks passed — create the series and its appointments atomically.
    series = new_record({
        "treatment_plan_id": plan["id"],
        "plan_phase_id": plan_phase["id"],
        "provider_id": provider_id,
        "treatment_room_id": treatment_room_id,
        "start_date": start_date,
        "weekday_pattern": list(weekday_pattern),
        "start_time_minutes": start_time_minutes,
        "duration_minutes": duration_minutes,
        "generated_count": 0,
        "status": "SCHEDULED",
    })
    db.appointment_series[series["id"]] = series

    for (start_iso, end_iso, _sd, _ed, counts_against_cap) in staged:
        appt = new_record({
            "patient_id": patient["id"],
            "appointment_series_id": series["id"],
            "plan_phase_id": plan_phase["id"],
            "provider_id": provider_id,
            "treatment_room_id": treatment_room_id,
            "insurance_policy_id": insurance_policy_id,
            "visit_type": plan_phase_visit_type(plan_phase),
            "replaces_appointment_id": None,
            "scheduled_start": start_iso,
            "scheduled_end": end_iso,
            "duration_minutes": duration_minutes,
            "counts_against_cap": counts_against_cap,
            "patient_responsibility_cents": 0,
            "insurance_paid_cents": 0,
            "no_show_fee_cents": 0,
            "attendance_status": "BOOKED",
            "billing_status": "UNBILLED",
        })
        db.appointments[appt["id"]] = appt
        if counts_against_cap and policy is not None:
            policy["visits_reserved"] += 1

    if policy is not None and cap_reservations > 0:
        touch(policy)

    series["generated_count"] = len(staged)
    return series


def plan_phase_visit_type(plan_phase):
    """Series-generated appointments are adjustments by clinical convention; the
    phase frequency materializes ADJUSTMENT visits."""
    return "ADJUSTMENT"
