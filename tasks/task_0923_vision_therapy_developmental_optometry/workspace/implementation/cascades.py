"""Shared multi-row side effects: the visit ledger, CASCADE-A (red flag),
CASCADE-B (discharge), and the assessment-finalize derivation chain."""

from datetime import timedelta

import calc
import config
from store import base_row, db, iso3, now, now_iso, parse_instant, touch


# ------------------------------------------------------- the visit ledger --
def consume_visit_unit(auth):
    """Scheduling draws exactly one unit (PRD §3.5)."""
    auth["visits_consumed"] += 1
    auth["visits_remaining"] -= 1
    if auth["visits_remaining"] <= 0 and auth["status"] == "ACTIVE":
        auth["status"] = "EXHAUSTED"
    touch(auth)


def release_visit_unit(session):
    """CASCADE-A hop 4 / CASCADE-B hop 3, and the manual-cancel release.

    Releasing is also the trigger point for the equipment-recall leg (hop 5):
    it fires only when the releasing session's plan is SUSPENDED for
    RED_FLAG_REFERRAL."""
    auth = db.authorizations.get(session.get("authorization_id"))
    if auth is None:
        return
    auth["visits_released"] += 1
    auth["visits_remaining"] += 1
    if auth["status"] == "EXHAUSTED":
        auth["status"] = "ACTIVE"
    touch(auth)
    recall_equipment_leg(db.plans.get(session.get("plan_id")))


def recall_equipment_leg(plan):
    """Hop 5.  Tests the suspension reason: only RED_FLAG_REFERRAL satisfies it."""
    if plan is None:
        return
    if plan.get("status") != "SUSPENDED" or plan.get("suspension_reason") != "RED_FLAG_REFERRAL":
        return
    stamp = now_iso()
    due = iso3(now() + timedelta(days=config.KIT_RECALL_DUE_DAYS))
    for loan in db.kit_loans.values():
        if loan["plan_id"] == plan["id"] and loan["status"] == "CHECKED_OUT":
            loan["status"] = "RECALLED"
            loan["recalled_at"] = stamp
            loan["recall_due_at"] = due
            touch(loan)


def cancel_session(session, reason):
    """Shared cancel body: manual cancel, CASCADE-A hop 3, CASCADE-B hop 2."""
    session["schedule_status"] = "CANCELLED"
    session["cancel_reason"] = reason
    session["billing_status"] = "NON_BILLABLE"
    touch(session)
    if session["modality"] == "IN_OFFICE":
        release_visit_unit(session)


# ------------------------------------------------- CASCADE-A, hops 2..5 ----
def suspend_plan(plan, reason):
    """Plan ACTIVE -> SUSPENDED, then hop 3 (cancel future sessions), which in
    turn drives hop 4 (release) and hop 5 (recall)."""
    plan["status"] = "SUSPENDED"
    plan["suspension_reason"] = reason
    touch(plan)
    cutoff = now()
    for session in list(db.sessions.values()):
        if session["plan_id"] != plan["id"]:
            continue
        if session["schedule_status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        start = parse_instant(session.get("scheduled_start_at"))
        if start is None or start < cutoff:
            continue
        cancel_session(session, "PLAN_SUSPENDED")


def create_referral_row(patient_id, direction, urgency, referring_provider_name,
                        target_provider_name, reason, plan_id=None,
                        triggering_assessment_id=None):
    """Creates the row and runs CASCADE-A hop 2.

    Hop 2 is written as a property of *creating* an outbound urgent referral
    that names an ACTIVE plan (PRD §3.11), so it fires for a manually created
    referral exactly as it does for a cascade-created one."""
    hours = (config.URGENT_REFERRAL_SLA_HOURS if urgency == "URGENT"
             else config.ROUTINE_REFERRAL_SLA_HOURS)
    row = base_row()
    row.update({
        "patient_id": patient_id,
        "plan_id": plan_id,
        "triggering_assessment_id": triggering_assessment_id,
        "direction": direction,
        "urgency": urgency,
        "referring_provider_name": referring_provider_name,
        "target_provider_name": target_provider_name,
        "reason": reason,
        "status": "SENT",
        "sla_due_at": iso3(now() + timedelta(hours=hours)),
        "responded_at": None,
        "response_outcome": None,
        "decline_reason": None,
        "attempt_count": 1,
        "sla_breached": False,
    })
    db.referrals[row["id"]] = row

    if direction == "OUTBOUND" and urgency == "URGENT" and plan_id:
        plan = db.plans.get(plan_id)
        if plan is not None and plan.get("status") == "ACTIVE":
            suspend_plan(plan, "RED_FLAG_REFERRAL")
    return row


# -------------------------------------------- assessment finalize chain ----
def finalize_assessment(assessment):
    """Everything POST /assessments/{id}/finalize writes, in PRD order."""
    calc.finalize_clinical_flags(assessment)
    assessment["status"] = "FINALIZED"
    touch(assessment)

    plan = db.plans.get(assessment.get("plan_id"))
    patient = db.patients.get(assessment["patient_id"])

    plateau_flag = False
    delta = None
    if assessment["assessment_type"] == "REASSESSMENT" and plan is not None:
        sym = calc.symptom_improvement_pct(plan, assessment)
        score = calc.composite_progress_score(patient, plan, assessment, sym)
        assessment["symptom_improvement_pct"] = sym
        assessment["composite_progress_score"] = score

        prior = calc.prior_signed_reassessment(plan["id"], assessment["id"])
        if prior is not None and prior.get("composite_progress_score") is not None:
            delta = calc.f2(calc.D(score) - calc.D(prior["composite_progress_score"]))
        assessment["improvement_delta_points"] = delta

        before = plan["consecutive_low_delta_count"]
        if delta is not None and calc.D(delta) < calc.D(config.PLATEAU_DELTA_POINTS):
            plan["consecutive_low_delta_count"] = before + 1
        else:
            plan["consecutive_low_delta_count"] = 0
        if plan["consecutive_low_delta_count"] != before:
            touch(plan)
        plateau_flag = plan["consecutive_low_delta_count"] >= config.PLATEAU_CONSECUTIVE_COUNT
        assessment["plateau_flag"] = plateau_flag

    # discharge_ready is recomputed at EVERY assessment finalize, and both
    # variants read only SIGNED assessments -- so the battery being finalized
    # never counts toward the recomputation its own finalize triggers.
    if plan is not None:
        ready = calc.discharge_readiness(plan)
        if plan["discharge_ready"] != ready:
            plan["discharge_ready"] = ready
            touch(plan)

    if assessment["assessment_type"] == "REASSESSMENT" and plan is not None:
        _progress_axis(plan, plateau_flag, delta)
        _phase_regression(plan, assessment)

    if assessment["red_flag_present"]:
        create_referral_row(
            patient_id=assessment["patient_id"],
            direction="OUTBOUND",
            urgency="URGENT",
            referring_provider_name=None,
            target_provider_name=None,
            reason=None,
            plan_id=assessment.get("plan_id"),
            triggering_assessment_id=assessment["id"],
        )


def _progress_axis(plan, plateau_flag, delta):
    state = plan["progress_state"]
    if state == "ON_TRACK":
        if plateau_flag:
            plan["progress_state"] = "PLATEAU"
            touch(plan)
        return
    if state != "PLATEAU":
        return
    # The recovery arm is evaluated first and pre-empts both forks.
    if delta is not None and calc.D(delta) >= calc.D(config.PLATEAU_DELTA_POINTS):
        plan["progress_state"] = "ON_TRACK"
        plan["consecutive_low_delta_count"] = 0
        touch(plan)
        return
    plan["progress_state"] = "DISCHARGE_PENDING" if plan["discharge_ready"] else "REVISION_PENDING"
    touch(plan)


def _phase_regression(plan, assessment):
    score = assessment.get("composite_progress_score")
    if score is None or calc.D(score) >= calc.D(config.REGRESSION_SCORE_THRESHOLD):
        return
    index = plan["current_phase_index"]
    if index <= 1:
        return
    current = _phase_at(plan["id"], index)
    below = _phase_at(plan["id"], index - 1)
    if below is None or below["status"] != "MASTERED":
        return
    if current is not None:
        current["status"] = "LOCKED"
        current["started_at"] = None
        touch(current)
    below["status"] = "IN_PROGRESS"
    below["mastered_at"] = None
    below["started_at"] = now_iso()
    touch(below)
    plan["current_phase_index"] = index - 1
    touch(plan)


def _phase_at(plan_id, sequence_index):
    for phase in db.phases.values():
        if phase["plan_id"] == plan_id and phase["sequence_index"] == sequence_index:
            return phase
    return None


def in_progress_phase(plan_id):
    for phase in db.phases.values():
        if phase["plan_id"] == plan_id and phase["status"] == "IN_PROGRESS":
            return phase
    return None


# --------------------------------------------------------- CASCADE-B ------
def discharge_cascade(patient):
    """Runs after the patient row has been moved to DISCHARGED."""
    plans = [p for p in db.plans.values()
             if p["patient_id"] == patient["id"]
             and p["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "UNDER_REVISION")]

    # Hop 1
    for plan in plans:
        plan["status"] = "DISCHARGED"
        touch(plan)

    # Hop 2 + hop 3 (no future-only filter here, unlike CASCADE-A hop 3).
    for plan in plans:
        for session in list(db.sessions.values()):
            if session["plan_id"] != plan["id"]:
                continue
            if session["schedule_status"] in ("SCHEDULED", "CHECKED_IN"):
                cancel_session(session, "PLAN_DISCHARGED")

    # Hop 5: only the authorizations the discharged plans were bound to.
    closed = set()
    for plan in plans:
        auth_id = plan.get("authorization_id")
        if not auth_id or auth_id in closed:
            continue
        auth = db.authorizations.get(auth_id)
        if auth is None or auth["status"] not in ("ACTIVE", "EXHAUSTED", "EXPIRED"):
            continue
        closed.add(auth_id)
        auth["status"] = "CLOSED"
        auth["close_reason"] = "PATIENT_DISCHARGED"
        touch(auth)

    # Separate fan-out: patching stops.
    for presc in db.occlusions.values():
        if presc["patient_id"] == patient["id"] and presc["status"] in ("ACTIVE", "TAPERED"):
            presc["status"] = "DISCONTINUED"
            touch(presc)
