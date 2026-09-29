"""Derived counters, readiness derivation, patient profile and cascades."""

from datetime import timedelta
from decimal import Decimal

import db
from db import DB, apply_changes, get, rows

COMMITTED_STATUSES = ("TENTATIVE", "CONFIRMED", "CHECKED_IN", "INFUSING", "OBSERVING")
TERMINAL_STATUSES = ("COMPLETED", "CANCELLED", "NO_SHOW")
BUMPABLE_STATUSES = ("TENTATIVE", "CONFIRMED")
UTILISATION_STATUSES = COMMITTED_STATUSES + ("COMPLETED",)

REMINDER_CAPS = {"STANDARD": 1, "ELEVATED": 3, "INTENSIVE": 5}
CADENCE_CODES = {"STANDARD": "C_STANDARD", "ELEVATED": "C_ELEVATED", "INTENSIVE": "C_INTENSIVE"}
ROLLING_WEIGHTS = (100, 85, 70, 55, 40, 25)
GRADE_EXTENSION = {1: 0, 2: 30, 3: 60, 4: 120}
CHAIR_UNIT_CENTS = 9000
STRIKE_WINDOW_DAYS = 180


# ---------------------------------------------------------------- lookups
def plan_of(appointment):
    return get("plans", appointment.get("treatment_plan_id"))


def drug_of_plan(plan):
    if plan is None:
        return None
    return get("drugs", plan.get("drug_id"))


def drug_of_appointment(appointment):
    return drug_of_plan(plan_of(appointment))


def center_of(appointment):
    return get("centers", appointment.get("center_id"))


def appointments_of_plan(plan_id):
    return [a for a in rows("appointments") if a.get("treatment_plan_id") == plan_id]


def appointments_of_patient(patient_id):
    return [a for a in rows("appointments") if a.get("patient_id") == patient_id]


def preps_of(appointment_id):
    return [p for p in rows("preps") if p.get("appointment_id") == appointment_id]


def events_of(appointment_id):
    return [e for e in rows("events") if e.get("appointment_id") == appointment_id]


def auths_of(appointment_id):
    return [a for a in rows("auths") if a.get("appointment_id") == appointment_id]


def reminders_of(appointment_id):
    return [r for r in rows("reminders") if r.get("appointment_id") == appointment_id]


def chairs_of_center(center_id):
    return [c for c in rows("chairs") if c.get("center_id") == center_id]


def nurses_of_center(center_id):
    return [n for n in rows("nurses") if n.get("center_id") == center_id]


def lots_of_drug(drug_id):
    return [lot for lot in rows("lots") if lot.get("drug_id") == drug_id]


# ---------------------------------------------------------------- counters
def recompute_center(center_id):
    center = get("centers", center_id)
    if center is None:
        return
    chairs = chairs_of_center(center_id)
    available = [c for c in chairs if c.get("status") == "AVAILABLE"]
    reserved = [c for c in available if c.get("reserved_for_urgent")]
    apply_changes(
        center,
        {"available_chair_count": len(available), "reserved_chair_count": len(reserved)},
    )


def recompute_chair(chair_id):
    chair = get("chairs", chair_id)
    if chair is None:
        return
    total = 0
    for appointment in rows("appointments"):
        if appointment.get("chair_id") == chair_id and appointment["schedule_status"] in COMMITTED_STATUSES:
            total += int(appointment.get("chair_minutes") or 0)
    apply_changes(chair, {"committed_minutes": total})


def recompute_nurse(nurse_id):
    nurse = get("nurses", nurse_id)
    if nurse is None:
        return
    total = 0
    for appointment in rows("appointments"):
        if appointment.get("nurse_id") == nurse_id and appointment["schedule_status"] in COMMITTED_STATUSES:
            total += int(appointment.get("acuity_points") or 0)
    apply_changes(nurse, {"assigned_acuity_points": total})


def recompute_lot(lot, extra=None):
    """Recompute the conserved unit counters and the derived lot status."""
    committed = administered = wasted = returned = 0
    for prep in rows("preps"):
        if prep.get("drug_lot_id") != lot["id"]:
            continue
        units = int(prep.get("units_requested") or 0)
        status = prep.get("status")
        if status == "REQUESTED" or status == "PREPARED":
            committed += units
        elif status == "ADMINISTERED":
            administered += units
        elif status == "WASTED":
            wasted += units
        elif status == "RETURNED":
            returned += units
    received = int(lot.get("units_received") or 0)
    if extra and "units_received" in extra:
        received = int(extra["units_received"])
    available = received - committed - administered - wasted
    status = lot.get("status")
    if status != "EXPIRED":
        if available <= 0:
            status = "DEPLETED"
        elif status == "DEPLETED":
            if lot.get("_expires_dt") is not None and lot["_expires_dt"] > db.now():
                status = "AVAILABLE"
        else:
            status = "AVAILABLE"
    changes = {
        "units_committed": committed,
        "units_administered": administered,
        "units_wasted": wasted,
        "units_returned": returned,
        "units_available": available,
        "status": status,
    }
    if extra:
        changes.update(extra)
    return apply_changes(lot, changes)


# ---------------------------------------------------------------- lab gate
def latest_resulted_draw(patient_id):
    candidates = [
        row
        for row in rows("labs")
        if row.get("patient_id") == patient_id and row.get("status") == "RESULTED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["_collected_dt"], r["_seq"]), reverse=True)
    return candidates[0]


def lab_gate(patient_id, drug, center):
    """Returns None on a pass, or the error id that the gate raises."""
    if drug is None or not drug.get("requires_lab_gate"):
        return None
    draw = latest_resulted_draw(patient_id)
    if draw is None:
        return "ERR_LAB_RESULT_MISSING"
    validity = int((center or {}).get("lab_validity_hours") or 0)
    age_hours = Decimal((db.now() - draw["_collected_dt"]).total_seconds()) / Decimal(3600)
    if age_hours > Decimal(validity):
        return "ERR_LAB_RESULT_STALE"
    min_anc = drug.get("lab_min_anc")
    min_plt = drug.get("lab_min_platelets")
    if min_anc is not None and draw.get("anc_value") is not None:
        if Decimal(str(draw["anc_value"])) < Decimal(str(min_anc)):
            return "ERR_LAB_GATE_NOT_MET"
    if min_plt is not None and draw.get("platelet_value") is not None:
        if Decimal(str(draw["platelet_value"])) < Decimal(str(min_plt)):
            return "ERR_LAB_GATE_NOT_MET"
    return None


def lab_condition(appointment):
    drug = drug_of_appointment(appointment)
    if drug is None or not drug.get("requires_lab_gate"):
        return True
    return lab_gate(appointment.get("patient_id"), drug, center_of(appointment)) is None


def auth_condition(appointment):
    for auth in auths_of(appointment["id"]):
        if auth.get("status") == "APPROVED":
            return True
    return False


def has_blocking_event(appointment_id):
    for event in events_of(appointment_id):
        if int(event.get("grade") or 0) >= 3 and event.get("status") in ("REPORTED", "UNDER_REVIEW"):
            return True
    return False


def derive_readiness(appointment):
    if has_blocking_event(appointment["id"]):
        return "BLOCKED"
    auth_ok = auth_condition(appointment)
    lab_ok = lab_condition(appointment)
    if auth_ok and lab_ok:
        return "FULLY_CLEARED"
    if auth_ok:
        return "AUTH_CLEARED"
    if lab_ok:
        return "LAB_CLEARED"
    return "PENDING"


def sync_readiness(appointment):
    """Persist the derived readiness; bumps version only when it actually moves."""
    return apply_changes(appointment, {"readiness_status": derive_readiness(appointment)})


def sync_readiness_for_patient(patient_id):
    for appointment in appointments_of_patient(patient_id):
        if appointment["schedule_status"] not in TERMINAL_STATUSES:
            sync_readiness(appointment)


# ---------------------------------------------------------------- risk score
def event_value(appointment):
    status = appointment["schedule_status"]
    if status == "NO_SHOW":
        return Decimal("1.00")
    if status == "CANCELLED":
        return Decimal("0.50") if appointment.get("late_cancellation") else Decimal("0.25")
    if status == "COMPLETED":
        return Decimal("0.00")
    return None


def terminal_history(patient_id):
    return [a for a in appointments_of_patient(patient_id) if a["schedule_status"] in TERMINAL_STATUSES]


def rolling_six(patient_id):
    history = terminal_history(patient_id)
    history.sort(key=lambda a: (a.get("service_date") or "", a["_seq"]), reverse=True)
    window = history[:6]
    if not window:
        return Decimal("0.00"), 0
    total_weight = 0
    weighted = Decimal(0)
    for index, appointment in enumerate(window):
        weight = ROLLING_WEIGHTS[index]
        total_weight += weight
        weighted += Decimal(weight) * event_value(appointment)
    if total_weight == 0:
        return Decimal("0.00"), len(window)
    score = db.rhu(weighted / Decimal(total_weight) * Decimal(100), 2)
    return score, len(window)


def quarter_bounds(day):
    quarter_index = (day.month - 1) // 3
    start_month = quarter_index * 3 + 1
    end_month = start_month + 2
    return start_month, end_month


def quarter_to_date(patient_id):
    day = db.clock_date()
    start_month, end_month = quarter_bounds(day)
    considered = []
    for appointment in terminal_history(patient_id):
        service_date = appointment.get("service_date") or ""
        try:
            year = int(service_date[0:4])
            month = int(service_date[5:7])
        except (ValueError, IndexError):
            continue
        if year == day.year and start_month <= month <= end_month:
            considered.append(appointment)
    if not considered:
        return Decimal("0.00"), 0
    no_shows = sum(1 for a in considered if a["schedule_status"] == "NO_SHOW")
    score = db.rhu(Decimal(no_shows) / Decimal(len(considered)) * Decimal(100), 2)
    return score, len(considered)


def tier_for(score):
    if score < Decimal("20"):
        return "STANDARD"
    if score < Decimal("45"):
        return "ELEVATED"
    return "INTENSIVE"


# ---------------------------------------------------------------- patient profile
def recompute_patient(patient):
    if patient is None:
        return
    history = appointments_of_patient(patient["id"])
    completed = sum(1 for a in history if a["schedule_status"] == "COMPLETED")
    window_start = db.clock_date() - timedelta(days=STRIKE_WINDOW_DAYS - 1)
    window_end = db.clock_date()
    strikes = 0
    for appointment in history:
        if appointment["schedule_status"] != "NO_SHOW":
            continue
        service_date = appointment.get("service_date")
        if not service_date:
            continue
        day = db.midnight(service_date).date()
        if window_start <= day <= window_end:
            strikes += 1
    score, _ = rolling_six(patient["id"])
    liability = sum(
        int(a.get("cancellation_charge_cents") or 0)
        for a in history
        if a["schedule_status"] == "CANCELLED"
    )
    steering = patient.get("steering_status") or "SUITE"
    flipped = False
    if steering == "SUITE" and (strikes >= 3 or liability >= 50000):
        steering = "HOME_INFUSION_REVIEW"
        flipped = True
    apply_changes(
        patient,
        {
            "completed_appointment_count": completed,
            "no_show_strikes": strikes,
            "no_show_risk_score": float(score),
            "reminder_tier": tier_for(score),
            "waste_liability_cents": liability,
            "steering_status": steering,
        },
    )
    if flipped:
        for plan in rows("plans"):
            if plan.get("patient_id") == patient["id"] and plan.get("status") == "ACTIVE":
                suspend_plan(plan)


def recompute_plan_cycles(plan):
    if plan is None:
        return
    completed = sum(
        1 for a in appointments_of_plan(plan["id"]) if a["schedule_status"] == "COMPLETED"
    )
    apply_changes(
        plan,
        {"completed_cycles": completed, "first_dose_completed": completed >= 1},
    )


# ---------------------------------------------------------------- preparations
def prep_lot(prep):
    return get("lots", prep.get("drug_lot_id"))


def prep_unit_cost(prep):
    lot = prep_lot(prep)
    drug = get("drugs", (lot or {}).get("drug_id"))
    return int((drug or {}).get("unit_cost_cents") or 0)


def prep_to_returned(prep):
    apply_changes(prep, {"status": "RETURNED"})
    lot = prep_lot(prep)
    if lot is not None:
        recompute_lot(lot)


def prep_to_wasted(prep):
    cost = int(prep.get("units_requested") or 0) * prep_unit_cost(prep)
    apply_changes(prep, {"status": "WASTED", "waste_cost_cents": cost})
    lot = prep_lot(prep)
    if lot is not None:
        recompute_lot(lot)
    return cost


def prep_to_administered(prep):
    apply_changes(prep, {"status": "ADMINISTERED"})
    lot = prep_lot(prep)
    if lot is not None:
        recompute_lot(lot)


def release_doses_for_cancellation(appointment):
    """REQUESTED doses go back to stock, PREPARED doses are wasted.

    Returns the total waste cost of the doses this cancellation just wasted.
    """
    waste = 0
    for prep in preps_of(appointment["id"]):
        if prep.get("status") == "REQUESTED":
            prep_to_returned(prep)
        elif prep.get("status") == "PREPARED":
            waste += prep_to_wasted(prep)
    return waste


# ---------------------------------------------------------------- cancellation
def cancellation_charge(appointment, waste_cents):
    start_instant = db.instant_of(appointment["service_date"], appointment.get("start_minute") or 0)
    late = db.now() >= (start_instant - timedelta(hours=24))
    if not late:
        base = 0
    elif appointment.get("booking_class") == "ROUTINE":
        base = 2500
    else:
        base = 4000
    provisional = base + waste_cents
    if provisional <= 5000:
        share = Decimal("0.00")
    elif provisional <= 25000:
        share = Decimal("0.20")
    else:
        share = Decimal("0.35")
    final = base + db.rhu_int(Decimal(waste_cents) * share)
    return late, final


def cancel_appointment(appointment, system=False):
    waste = release_doses_for_cancellation(appointment)
    if system:
        late, charge = False, 0
    else:
        late, charge = cancellation_charge(appointment, waste)
    chair_id = appointment.get("chair_id")
    nurse_id = appointment.get("nurse_id")
    apply_changes(
        appointment,
        {
            "schedule_status": "CANCELLED",
            "late_cancellation": late,
            "cancellation_charge_cents": charge,
        },
    )
    recompute_chair(chair_id)
    recompute_nurse(nurse_id)
    recompute_patient(get("patients", appointment.get("patient_id")))


def suspend_plan(plan):
    """ACTIVE -> SUSPENDED with the zero-charge cancellation cascade."""
    if plan.get("status") != "ACTIVE":
        return
    apply_changes(plan, {"status": "SUSPENDED"})
    cancel_live_visits(plan)


def cancel_live_visits(plan):
    for appointment in appointments_of_plan(plan["id"]):
        if appointment["schedule_status"] in BUMPABLE_STATUSES:
            cancel_appointment(appointment, system=True)


# ---------------------------------------------------------------- bump path
def bump_appointment(appointment):
    """Demote to TENTATIVE and release the chair and nurse."""
    if appointment["schedule_status"] not in BUMPABLE_STATUSES:
        return False
    chair_id = appointment.get("chair_id")
    nurse_id = appointment.get("nurse_id")
    moved = apply_changes(
        appointment,
        {"schedule_status": "TENTATIVE", "chair_id": None, "nurse_id": None},
    )
    recompute_chair(chair_id)
    recompute_nurse(nurse_id)
    return moved


def bump_visits_of_chair(chair_id):
    for appointment in rows("appointments"):
        if appointment.get("chair_id") == chair_id:
            bump_appointment(appointment)


def bump_visits_of_nurse(nurse_id):
    for appointment in rows("appointments"):
        if appointment.get("nurse_id") == nurse_id:
            bump_appointment(appointment)


def bump_colliding_visits(appointment):
    """Re-evaluate a lengthened window against the buffered occupancy rule."""
    chair_id = appointment.get("chair_id")
    if chair_id is None:
        return
    center = center_of(appointment)
    buffer_minutes = int((center or {}).get("turnover_buffer_minutes") or 0)
    start = int(appointment.get("start_minute") or 0)
    end = int(appointment.get("end_minute") or 0)
    for other in rows("appointments"):
        if other["id"] == appointment["id"]:
            continue
        if other.get("chair_id") != chair_id:
            continue
        if other.get("service_date") != appointment.get("service_date"):
            continue
        if other["schedule_status"] not in BUMPABLE_STATUSES:
            continue
        other_start = int(other.get("start_minute") or 0)
        other_end = int(other.get("end_minute") or 0)
        if other_start < end + buffer_minutes and start < other_end + buffer_minutes:
            bump_appointment(other)
