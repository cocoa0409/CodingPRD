"""The system-actor transitions: every state change that is caused by another
state change rather than by the request itself. Each helper here is written so
that it can be called from any of the endpoints that trigger it, which is what
keeps the multi-hop chains identical no matter which door they were entered by.
"""
from calc import BLOCKED_REASON
from store import base_record, ordered, store, touch

OPEN_TASK_STATUSES = ("PENDING", "ATTEMPTED", "REACHED")
LIVE_ADVICE_STATUSES = ("AUTHORIZED", "OVERRIDDEN")


# ---------------------------------------------------------------------------
# Conserved counters
# ---------------------------------------------------------------------------
def reevaluate_eligibility(nurse):
    """A nurse is OFF_ROTATION exactly while pending_high_risk_count has reached
    high_risk_cap; the flag is re-derived after every change to the count."""
    if nurse["pending_high_risk_count"] >= nurse["high_risk_cap"]:
        nurse["intake_eligibility"] = "OFF_ROTATION"
    else:
        nurse["intake_eligibility"] = "ON_ROTATION"


def add_high_risk(nurse):
    nurse["pending_high_risk_count"] += 1
    reevaluate_eligibility(nurse)
    touch(nurse)


def release_high_risk(nurse):
    if nurse["pending_high_risk_count"] > 0:
        nurse["pending_high_risk_count"] -= 1
    reevaluate_eligibility(nurse)
    touch(nurse)


def add_call_load(nurse, delta):
    nurse["active_call_load"] = max(0, nurse["active_call_load"] + delta)
    touch(nurse)


def credit_practice_ledger(practice, minutes, cents):
    practice["billed_advice_minutes_total"] += minutes
    practice["advice_fee_accrued_cents"] += cents
    touch(practice)


def debit_practice_ledger(practice, minutes, cents):
    practice["billed_advice_minutes_total"] = max(
        0, practice["billed_advice_minutes_total"] - minutes)
    practice["advice_fee_accrued_cents"] = max(
        0, practice["advice_fee_accrued_cents"] - cents)
    touch(practice)


def open_callback(practice):
    practice["open_callback_count"] += 1
    touch(practice)


def close_callback(practice):
    if practice["open_callback_count"] > 0:
        practice["open_callback_count"] -= 1
    touch(practice)


# ---------------------------------------------------------------------------
# CallbackTask creation and cancellation
# ---------------------------------------------------------------------------
def create_callback_task(disposition, call, requirement):
    task = base_record()
    task.update({
        "disposition_id": disposition["id"],
        "practice_id": call["practice_id"],
        "assigned_nurse_id": disposition["determined_by_nurse_id"],
        "risk_class": requirement["risk_class"],
        "due_by_utc": requirement["due_by_utc"],
        "attempt_count": 0,
        "max_attempts": requirement["max_attempts"],
        "last_attempt_outcome": None,
        "patient_condition": None,
        "advice_followed": None,
        "verifier_attestation": None,
        "verified_by_nurse_id": None,
        "verified_at": None,
        "status": "PENDING",
    })
    store.callback_tasks[task["id"]] = task
    practice = store.practices.get(call["practice_id"])
    if practice is not None:
        open_callback(practice)
    return task


def tasks_of_disposition(disposition_id):
    return [t for t in ordered(store.callback_tasks)
            if t["disposition_id"] == disposition_id]


def cancel_open_tasks(disposition):
    """HOP: an open CallbackTask of a dead disposition becomes CANCELLED and
    leaves the practice's open set."""
    cancelled = []
    for task in tasks_of_disposition(disposition["id"]):
        if task["status"] not in OPEN_TASK_STATUSES:
            continue
        task["status"] = "CANCELLED"
        touch(task)
        practice = store.practices.get(task["practice_id"])
        if practice is not None:
            close_callback(practice)
        cancelled.append(task)
    return cancelled


# ---------------------------------------------------------------------------
# The variance escalation chain: Disposition -> Practice -> CoverageWindow
# ---------------------------------------------------------------------------
def block_draft_coverage_windows(practice):
    for window in ordered(store.coverage_windows):
        if window["practice_id"] != practice["id"]:
            continue
        if window["status"] != "DRAFT":
            continue
        window["status"] = "BLOCKED"
        window["suspend_reason"] = BLOCKED_REASON
        touch(window)


def register_variance(practice):
    """HOP 2/3/4 of every variance cascade."""
    practice["open_variance_count"] += 1
    if practice["open_variance_count"] >= practice["variance_review_threshold"]:
        practice["compliance_posture"] = "UNDER_REVIEW"
    touch(practice)
    if practice["compliance_posture"] == "UNDER_REVIEW":
        block_draft_coverage_windows(practice)


def escalate_variance(disposition, bump_version=True):
    """HOP 1: audit_status -> VARIANCE_ESCALATED, then the practice chain. Only
    ever entered from AWAITING_OUTCOME or OUTCOME_RECORDED."""
    disposition["audit_status"] = "VARIANCE_ESCALATED"
    if bump_version:
        touch(disposition)
    call = store.calls.get(disposition["call_id"])
    practice = store.practices.get(call["practice_id"]) if call else None
    if practice is not None:
        register_variance(practice)


# ---------------------------------------------------------------------------
# Disposition voiding — shared by the re-assessment loop and by abandon
# ---------------------------------------------------------------------------
def clear_warm_transfer_hold(disposition, call):
    """When the disposition that raised the EMERGENCY_911 hold dies, the hold
    dies with it: the call flag clears and the nurse gets its slot back."""
    if not call["requires_warm_transfer"]:
        return
    call["requires_warm_transfer"] = False
    touch(call)
    nurse = store.nurses.get(disposition["determined_by_nurse_id"])
    if nurse is not None:
        release_high_risk(nurse)


def void_disposition(disposition, call):
    """advice_status -> VOIDED plus its two downstream hops. audit_status is
    deliberately untouched: the two dimensions are independent."""
    if disposition["advice_status"] not in LIVE_ADVICE_STATUSES:
        return False
    disposition["advice_status"] = "VOIDED"
    touch(disposition)
    cancel_open_tasks(disposition)
    if disposition["final_level"] == "EMERGENCY_911":
        clear_warm_transfer_hold(disposition, call)
    return True


def supersede_active_assessments(call, keep_id=None):
    """HOP 1 of the re-assessment loop, and HOPs 2-4 by consequence."""
    for assessment in ordered(store.assessments):
        if assessment["call_id"] != call["id"]:
            continue
        if assessment["id"] == keep_id:
            continue
        if assessment["status"] != "ACTIVE":
            continue
        assessment["status"] = "SUPERSEDED"
        touch(assessment)
        for disposition in ordered(store.dispositions):
            if disposition["assessment_id"] != assessment["id"]:
                continue
            void_disposition(disposition, call)


def void_call_dispositions(call):
    """The abandon path: every live disposition of the call dies at once."""
    for disposition in ordered(store.dispositions):
        if disposition["call_id"] != call["id"]:
            continue
        void_disposition(disposition, call)


def active_assessment_of(call_id):
    for assessment in ordered(store.assessments):
        if assessment["call_id"] == call_id and assessment["status"] == "ACTIVE":
            return assessment
    return None
