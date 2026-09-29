"""State machines, cascades and the shared safety/temporal predicates."""
from datetime import timedelta

from flask import g

import calc
from calc import (SEAT_HOLDING_STATUSES, LIVE_PLACEMENT_STATUSES,
                  SEAT_CHANGEOVER_BUFFER_DAYS,
                  COMPLIANCE_STRIKE_SUSPENSION_THRESHOLD,
                  PROGRESSION_REVIEW_INTERVAL_DAYS)
from errors import fail
from store import db, stamp_new, touch
from util import parse_date, days_between

# ------------------------------------------------------ terminal state sets
TERMINAL_STATES = {
    "restriction_set": ("SUPERSEDED", "EXPIRED"),
    "placement": ("COMPLETED", "TERMINATED_EARLY", "DECLINED"),
    "directive": ("SUPERSEDED",),
    "progression_review": ("ADVANCED", "EXTENDED", "ESCALATED"),
    "case_review": ("DECIDED_CONTINUE", "DECIDED_MODIFY", "DECIDED_TERMINATE"),
    "training_record": ("SUPERSEDED",),
}


def check_terminal(kind, current_state):
    """Priority 8 - terminal-state lockdown, always before the from-state check."""
    if current_state in TERMINAL_STATES[kind]:
        fail("ERR_ALREADY_TERMINAL",
             "The addressed row is already in terminal state %s." % current_state)


def check_from_state(current_state, allowed):
    """Priority 9 - the row's state must be a declared origin of the transition."""
    if current_state not in allowed:
        fail("ERR_INVALID_STATE",
             "State %s is not an origin state for this transition."
             % current_state)


# ------------------------------------------------------------- predicates
def restriction_breach(rs, job, scheduled_hours=None):
    """Priority 19 - hard restriction limits."""
    if job["demand_lift_lbs"] > rs["max_lift_lbs"]:
        return True
    if job["demand_standing_minutes"] > rs["max_continuous_standing_minutes"]:
        return True
    if job["demand_hours_per_day"] > rs["max_hours_per_day"]:
        return True
    if job["demand_keyboard_minutes_per_hour"] > rs["keyboard_minutes_per_hour"]:
        return True
    if job["requires_overhead_reach"] and not rs["overhead_reach_allowed"]:
        return True
    if job["requires_driving"] and not rs["driving_allowed"]:
        return True
    if scheduled_hours is not None and scheduled_hours > rs["max_hours_per_day"]:
        return True
    return False


def job_demand_breach(rs, job):
    """The job-side subset used by the restriction-activation cascade."""
    return restriction_breach(rs, job, None)


def worker_window_overlap(employee_id, start, end, exclude_placement_id=None):
    """Priority 26 - HALF-OPEN [start_date, end_date) on the Employee."""
    for p in db.placements.values():
        if exclude_placement_id and p["id"] == exclude_placement_id:
            continue
        if p["placement_status"] not in LIVE_PLACEMENT_STATUSES:
            continue
        claim = db.claims.get(p["claim_id"])
        if not claim or claim["employee_id"] != employee_id:
            continue
        other_start = parse_date(p["start_date"])
        other_end = parse_date(p["end_date"])
        if start < other_end and other_start < end:
            return True
    return False


def job_changeover_conflict(job_id, start, exclude_placement_id=None):
    """Priority 27 - CLOSED interval + 1-day changeover buffer on the job."""
    for p in calc.placements_of_job(job_id):
        if exclude_placement_id and p["id"] == exclude_placement_id:
            continue
        if p["placement_status"] not in SEAT_HOLDING_STATUSES:
            continue
        occupant_end = parse_date(p["end_date"])
        gap = days_between(occupant_end, start)
        if 0 <= gap <= SEAT_CHANGEOVER_BUFFER_DAYS:
            return True
    return False


def job_seat_unavailable(job, start, end, exclude_placement_id=None):
    """Priority 29 - per-day aggregate seat capacity on the job."""
    occupants = []
    for p in calc.placements_of_job(job["id"]):
        if exclude_placement_id and p["id"] == exclude_placement_id:
            continue
        if p["placement_status"] not in SEAT_HOLDING_STATUSES:
            continue
        occupants.append((parse_date(p["start_date"]), parse_date(p["end_date"])))
    cursor = start
    while cursor <= end:
        count = sum(1 for (s, e) in occupants if s <= cursor <= e)
        if count + 1 > job["seat_capacity"]:
            return True
        cursor = cursor + timedelta(days=1)
    return False


# ------------------------------------------------------------ constructors
def new_case_review(placement_id, trigger_reason, opened_by_user_id,
                    quorum_required=3):
    row = stamp_new({
        "placement_id": placement_id,
        "trigger_reason": trigger_reason,
        "review_status": "OPEN",
        "quorum_required": quorum_required,
        "opened_by_user_id": opened_by_user_id,
        "closed_by_user_id": None,
    })
    db.case_reviews[row["id"]] = row
    return row


def new_progression_review(placement_id, step_index, due_date):
    row = stamp_new({
        "placement_id": placement_id,
        "step_index": step_index,
        "due_date": due_date.isoformat(),
        "review_status": "SCHEDULED",
        "deferral_count": 0,
        "reviewed_by_user_id": None,
        "target_hours_per_day": None,
        "target_lift_lbs": None,
        "outcome_note": None,
    })
    db.progression_reviews[row["id"]] = row
    return row


# ------------------------------------------------------------ side effects
def supersede_live_directives(placement):
    for directive in calc.directives_of_placement(placement["id"]):
        if directive["directive_status"] in ("PENDING", "AUTHORIZED",
                                             "AUTHORIZED_WITH_CONDITIONS"):
            directive["directive_status"] = "SUPERSEDED"
            touch(directive)


def move_placement_to_hold(placement, trigger_reason, opened_by="system"):
    """Placement ACTIVE -> PROGRESSION_HOLD with its panel."""
    placement["placement_status"] = "PROGRESSION_HOLD"
    touch(placement)
    existing = [c for c in calc.case_reviews_of_placement(placement["id"])
                if c["review_status"] in ("OPEN", "VOTING")]
    if not existing:
        new_case_review(placement["id"], trigger_reason, opened_by)


def end_placement(placement, destination, reason=None):
    """Shared closure effects for COMPLETED / TERMINATED_EARLY / DECLINED."""
    if destination == "DECLINED":
        placement["placement_status"] = "DECLINED"
        if reason is not None:
            placement["decline_reason"] = reason
        supersede_live_directives(placement)
    else:
        placement["placement_status"] = destination
        placement["ended_on"] = db.today().isoformat()
        supersede_live_directives(placement)
    touch(placement)


def recompute_surveillance_risk(placement):
    placement["reinjury_risk_score"] = calc.reinjury_risk_surveillance(placement)
    placement["reinjury_risk_variant"] = "SURVEILLANCE"


# --------------------------------------------- compliance dimension machine
COMPLIANCE_TRANSITIONS = {
    ("COMPLIANT", "MINOR"): "WATCH",
    ("COMPLIANT", "MAJOR"): "WATCH",
    ("COMPLIANT", "CRITICAL"): "NONCOMPLIANT",
    ("WATCH", "MAJOR"): "NONCOMPLIANT",
    ("WATCH", "CRITICAL"): "NONCOMPLIANT",
    ("WATCH", "NONE"): "COMPLIANT",
    ("NONCOMPLIANT", "NONE"): "REMEDIATED",
    ("REMEDIATED", "NONE"): "COMPLIANT",
}


def apply_compliance_finding(placement, finding_severity):
    key = (placement["compliance_status"], finding_severity)
    destination = COMPLIANCE_TRANSITIONS.get(key)
    if destination is None:
        return
    placement["compliance_status"] = destination
    touch(placement)
    if destination == "WATCH":
        recompute_surveillance_risk(placement)
    elif destination == "NONCOMPLIANT":
        recompute_surveillance_risk(placement)
        _noncompliant_cascade(placement)


def _noncompliant_cascade(placement):
    """CASCADE L2-L4 behind a move into NONCOMPLIANT."""
    supervisor = db.supervisors.get(placement["supervisor_id"])
    if supervisor is None:
        return
    effective = calc.supervisor_effective_strike_points(supervisor)
    if (supervisor["oversight_status"] != "ACTIVE"
            or effective < COMPLIANCE_STRIKE_SUSPENSION_THRESHOLD):
        return
    supervisor["oversight_status"] = "SUSPENDED"
    touch(supervisor)
    for job in calc.ordered_jobs_of_supervisor(supervisor["id"]):
        if job["job_status"] == "OPEN":
            job["job_status"] = "PAUSED"
            touch(job)
    for sibling in calc.placements_of_supervisor(supervisor["id"]):
        if sibling["id"] == placement["id"]:
            continue
        if (sibling["placement_status"] in ("ACTIVE", "PROGRESSION_HOLD")
                and sibling["compliance_status"] == "COMPLIANT"):
            sibling["compliance_status"] = "WATCH"
            touch(sibling)
