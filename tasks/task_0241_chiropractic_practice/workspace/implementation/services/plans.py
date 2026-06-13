"""Treatment plan / phase progression and cascades (PRD §2.5, §3.3, §3.4, §3.7)."""
import db
from models import touch


def phases_of(plan_id):
    return [p for p in db.plan_phases.values() if p["treatment_plan_id"] == plan_id]


def recompute_plan_totals(plan):
    """total_planned_visits = sum of planned_visit_count over non-CANCELLED phases."""
    total = 0
    for p in phases_of(plan["id"]):
        if p["status"] != "CANCELLED":
            total += p["planned_visit_count"]
    if plan["total_planned_visits"] != total:
        plan["total_planned_visits"] = total
        touch(plan)


def advance_after_phase_completion(plan, completed_phase):
    """A phase reached COMPLETED — advance forward or bubble up to plan completion
    (PRD §3.4).
    """
    siblings = phases_of(plan["id"])
    # Next PENDING phase of higher sequence_index, with no lower-index phase still
    # PENDING/IN_PROGRESS.
    higher_pending = sorted(
        [p for p in siblings if p["status"] == "PENDING"
         and p["sequence_index"] > completed_phase["sequence_index"]],
        key=lambda p: p["sequence_index"],
    )
    if higher_pending:
        # Only advance if no lower-index phase remains PENDING/IN_PROGRESS.
        nxt = higher_pending[0]
        blocking = [p for p in siblings
                    if p["sequence_index"] < nxt["sequence_index"]
                    and p["status"] in ("PENDING", "IN_PROGRESS")]
        if not blocking:
            nxt["status"] = "IN_PROGRESS"
            touch(nxt)
            plan["current_phase"] = nxt["phase_type"]
            touch(plan)
        return
    # No higher pending phase. If the completed phase was the highest index and
    # MAINTENANCE, the plan completes.
    max_index = max(p["sequence_index"] for p in siblings)
    if completed_phase["sequence_index"] == max_index and completed_phase["phase_type"] == "MAINTENANCE":
        if plan["status"] == "ACTIVE":
            plan["status"] = "COMPLETED"
            touch(plan)


def on_visit_attended(appt):
    """Bump phase/plan counters when an appointment reaches ATTENDED, and run
    phase-completion bubble-up if the phase fills (PRD §3.7 + §3.4).
    """
    phase_id = appt.get("plan_phase_id")
    if not phase_id:
        return
    phase = db.plan_phases.get(phase_id)
    if not phase:
        return
    phase["visits_completed"] += 1
    touch(phase)
    plan = db.treatment_plans.get(phase["treatment_plan_id"])
    if plan:
        plan["visits_delivered"] += 1
        touch(plan)
        if phase["status"] == "IN_PROGRESS" and phase["visits_completed"] >= phase["planned_visit_count"]:
            phase["status"] = "COMPLETED"
            touch(phase)
            advance_after_phase_completion(plan, phase)


def cancel_release_appointment(appt):
    """Cancel-release a still-BOOKED/CHECKED_IN appointment (release cap slot)."""
    from services.scheduling import release_cap_for_appointment
    if appt["attendance_status"] in ("BOOKED", "CHECKED_IN"):
        release_cap_for_appointment(appt)
        appt["attendance_status"] = "CANCELLED"
        touch(appt)


def cancel_series(series):
    """Cancel a SCHEDULED series and cancel-release its still-BOOKED appointments."""
    if series["status"] != "SCHEDULED":
        return
    series["status"] = "CANCELLED"
    touch(series)
    for appt in db.appointments.values():
        if appt.get("appointment_series_id") == series["id"]:
            cancel_release_appointment(appt)


def discontinue_plan(plan):
    """ACTIVE -> DISCONTINUED with cascades (PRD §3.3, §2.5)."""
    plan["status"] = "DISCONTINUED"
    touch(plan)
    for p in phases_of(plan["id"]):
        if p["status"] not in ("COMPLETED", "CANCELLED"):
            p["status"] = "CANCELLED"
            touch(p)
    for s in db.appointment_series.values():
        if s["treatment_plan_id"] == plan["id"] and s["status"] == "SCHEDULED":
            cancel_series(s)


def dismiss_patient(patient):
    """Dismissal cascade (PRD §3.7): cancel-release every BOOKED/CHECKED_IN
    appointment for the patient and discontinue any ACTIVE plan.
    """
    patient["is_dismissed"] = True
    patient["status"] = "DISMISSED"
    touch(patient)
    for appt in db.appointments.values():
        if appt["patient_id"] == patient["id"]:
            cancel_release_appointment(appt)
    for plan in db.treatment_plans.values():
        if plan["patient_id"] == patient["id"] and plan["status"] == "ACTIVE":
            discontinue_plan(plan)
