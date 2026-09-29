"""Cascade propagation and counter conservation (PRD 2.8).

Cascades are transitive and immediate: a write recounts the parent center, re-derives
its posture, re-derives every affected cycle's reviewer readiness score and applies
the two purely system-driven PREP <-> PREP_BLOCKED transitions inside the same
request. Counters are always rewritten from the primary records, never adjusted, so
compensating actions land exactly on their pre-operation values.
"""
import calc
from common import D, days, new_record, num
from store import clock_now, db

# Cycles that have not yet been decided (VERIFIED and DENIED are terminal).
NON_DECIDED = (
    "PREP",
    "PREP_BLOCKED",
    "SUBMITTED",
    "SITE_VISIT_SCHEDULED",
    "UNDER_REVIEW",
    "CONTINGENCY",
)

# PRD 3.3: the statuses refreshed when an abstraction is submitted.
ABSTRACTION_REFRESH_STATUSES = (
    "PREP",
    "PREP_BLOCKED",
    "SUBMITTED",
    "SITE_VISIT_SCHEDULED",
    "UNDER_REVIEW",
)


# --- center counters -------------------------------------------------------


def recount_center(center):
    """Rewrite every derived counter of the center from its primary records."""
    center_id = center["id"]
    cases = calc.cases_of_center(center_id)
    center["registry_included_case_count"] = len(
        [c for c in cases if c["inclusion_status"] == "INCLUDED"]
    )
    center["registry_excluded_case_count"] = len(
        [c for c in cases if c["inclusion_status"] == "EXCLUDED"]
    )
    center["open_pi_event_count"] = calc.open_pi_event_count(center_id)
    center["closed_pi_event_count"] = calc.closed_pi_event_count(center_id)
    center["open_critical_deficiency_count"] = calc.open_critical_deficiency_count(center_id)
    center["escalated_critical_deficiency_count"] = calc.escalated_critical_deficiency_count(
        center_id
    )
    center["outreach_credit_hours_ytd"] = num(calc.outreach_ledger(center_id))


def refresh_posture(center):
    center["readiness_posture"] = calc.readiness_posture(center)


def posture_of(center):
    """Live posture, so that merely advancing the clock past a loop-closure due
    date degrades the posture with no write against the center (PRD 3.7)."""
    return calc.readiness_posture(center)


# --- triage rates and the under-triage alert cascade ----------------------


def recompute_rates(center):
    rates = calc.triage_rates(center["id"], "PROVISIONAL_MONITORING")
    center["under_triage_rate_pct"] = num(rates["under_triage_rate_pct"])
    center["over_triage_rate_pct"] = num(rates["over_triage_rate_pct"])
    return maybe_open_under_triage_event(center)


def maybe_open_under_triage_event(center):
    """PRD 3.5 hop 2: only an *open* under-triage loop suppresses a new one."""
    if D(center["under_triage_rate_pct"]) < calc.UNDER_TRIAGE_ALERT_PCT:
        return None
    for event in calc.pi_events_of_center(center["id"]):
        if event["event_type"] == "UNDER_TRIAGE" and event["status"] in calc.OPEN_PI_STATUSES:
            return None
    return create_pi_event(center, "UNDER_TRIAGE", "HIGH", due_days=calc.LOOP_CLOSURE_DAYS)


# --- PI event creation ----------------------------------------------------


def create_pi_event(
    center,
    event_type,
    severity,
    case_id=None,
    source_deficiency_id=None,
    due_days=calc.LOOP_CLOSURE_DAYS,
    origin="SYSTEM_AUTO",
):
    now = clock_now()
    record = new_record()
    record.update(
        {
            "center_id": center["id"],
            "case_id": case_id,
            "source_deficiency_id": source_deficiency_id,
            "event_type": event_type,
            "severity": severity,
            "status": "IDENTIFIED",
            "origin": origin,
            "opened_at": now,
            "loop_closure_due_at": now + days(due_days),
            "closed_at": None,
            "review_round": 1,
            "corrective_action_count": 0,
            "verified_action_count": 0,
        }
    )
    db.pi_events[record["id"]] = record
    return record


def refresh_event_action_counts(event):
    actions = calc.actions_of_event(event["id"])
    event["corrective_action_count"] = len(actions)
    event["verified_action_count"] = len(
        [a for a in actions if a["completion_status"] == "VERIFIED"]
    )


# --- verification cycles --------------------------------------------------


def refresh_cycle_counts(cycle):
    counts = calc.cycle_open_class_counts(cycle["id"])
    cycle["open_type_i_count"] = counts["TYPE_I_CRITICAL"]
    cycle["open_type_ii_count"] = counts["TYPE_II_MAJOR"]
    cycle["open_type_iii_count"] = counts["TYPE_III_MINOR"]


def store_readiness(cycle):
    score = calc.readiness_score(cycle, "REVIEWER_ASSESSMENT")
    cycle["readiness_score"] = num(score)
    return score


def apply_prep_gate(cycle):
    """The two purely system-driven transitions of PRD 2.8. A cycle also stays
    blocked while a TYPE_I_CRITICAL deficiency of its own is still open (PRD 3.9)."""
    score = D(cycle["readiness_score"])
    blocked = score < calc.SUBMIT_MIN_READINESS or cycle["open_type_i_count"] >= 1
    if cycle["status"] == "PREP" and blocked:
        cycle["status"] = "PREP_BLOCKED"
    elif cycle["status"] == "PREP_BLOCKED" and not blocked:
        cycle["status"] = "PREP"


def refresh_cycle(cycle, gate=True):
    refresh_cycle_counts(cycle)
    store_readiness(cycle)
    if gate:
        apply_prep_gate(cycle)


def refresh_cycles(center, statuses=NON_DECIDED, gate=True):
    for cycle in calc.cycles_of_center(center["id"]):
        if cycle["status"] in statuses:
            refresh_cycle(cycle, gate=gate)


# --- the entry point every mutating route calls ---------------------------


def cascade_center(center, rates=False, cycles=False, cycle_statuses=NON_DECIDED):
    """Recount the center, re-derive its posture and (at the declared triggers
    only) re-derive its cycles' readiness scores."""
    if center is None:
        return
    opened = None
    if rates:
        opened = recompute_rates(center)
    recount_center(center)
    refresh_posture(center)
    # a threshold-opened PI event is itself a declared trigger for cycle readiness
    if cycles or opened is not None:
        refresh_cycles(center, cycle_statuses)


def apply_inclusion_and_cascade(case, center, rates=False, cycles=False):
    calc.apply_inclusion(case)
    cascade_center(center, rates=rates, cycles=cycles)
