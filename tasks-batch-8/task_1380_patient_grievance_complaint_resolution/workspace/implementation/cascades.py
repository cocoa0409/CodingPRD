"""Cascade side effects (SCAFFOLD §1.2 state machine side_effects).

Every cascaded child resource gets its own updated_at refresh and version bump.
"""

from datetime import timedelta

import db
import derived
from clock import business_due, iso_ms, parse_iso
from helpers import new_id, stamp_new, touch
from state import CLOCK


def close_suspensions_for_case(case, now):
    """Every OPEN ClockSuspension -> CLOSED at the given instant."""
    for s in derived.case_suspensions(case["id"]):
        if s["status"] == "OPEN":
            s["status"] = "CLOSED"
            s["closed_at"] = iso_ms(now)
            s["credited_seconds"] = int((now - parse_iso(s["started_at"])).total_seconds())
            touch(s)


def complete_assignments_for_case(case):
    """Every ACTIVE CaseAssignment -> COMPLETED (case reached CLOSED)."""
    for a in db.case_assignments.values():
        if a["case_id"] == case["id"] and a["status"] == "ACTIVE":
            a["status"] = "COMPLETED"
            touch(a)


def create_follow_up(case, now):
    """SatisfactionFollowUp spawned at closure; due/expires derive on read."""
    followup = stamp_new()
    followup.update(
        {
            "case_id": case["id"],
            "status": "PENDING",
            "_base_closed_at": now.isoformat(),
            "score": None,
            "responded_at": None,
        }
    )
    db.follow_ups[followup["id"]] = followup
    return followup


def close_case(case, now, closure_note):
    """Shared closure cascade (letter issue and complaint fast-track close).

    Stamps closed_at, judges timeliness against the binding calendar due
    (equality is ON_TIME), completes assignments, closes open suspensions,
    spawns the satisfaction follow-up, and bumps the case version.
    """
    cal_due, _, _ = derived.response_dues(case, now)
    case["lifecycle_status"] = "CLOSED"
    case["closed_at"] = iso_ms(now)
    case["closure_note"] = closure_note
    if cal_due is not None and now > cal_due:
        case["resolution_timeliness"] = "LATE"
    else:
        case["resolution_timeliness"] = "ON_TIME"
    case["_closure_due_calendar_at"] = cal_due.isoformat() if cal_due else None
    complete_assignments_for_case(case)
    close_suspensions_for_case(case, now)
    create_follow_up(case, now)
    touch(case)


def withdraw_case(case, now):
    """Withdraw cascade (PRD §3.9).

    ACTIVE assignments -> RELEASED; investigation in OPEN/FINDINGS_SUBMITTED/
    REOPENED -> CANCELLED; letters in DRAFT/IN_REVIEW/RETURNED -> CANCELLED
    (APPROVED stays APPROVED); OPEN suspensions close; PENDING_APPROVAL
    recovery actions -> REJECTED.
    """
    case["lifecycle_status"] = "WITHDRAWN"
    for a in db.case_assignments.values():
        if a["case_id"] == case["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            a["released_at"] = iso_ms(now)
            touch(a)
    for inv in db.investigations.values():
        if inv["case_id"] == case["id"] and inv["status"] in (
            "OPEN",
            "FINDINGS_SUBMITTED",
            "REOPENED",
        ):
            inv["status"] = "CANCELLED"
            touch(inv)
    for letter in db.response_letters.values():
        if letter["case_id"] == case["id"] and letter["status"] in (
            "DRAFT",
            "IN_REVIEW",
            "RETURNED",
        ):
            letter["status"] = "CANCELLED"
            touch(letter)
    close_suspensions_for_case(case, now)
    for action in db.recovery_actions.values():
        if action["case_id"] == case["id"] and action["status"] == "PENDING_APPROVAL":
            action["status"] = "REJECTED"
            touch(action)
    touch(case)


def reopen_case(case, now):
    """Reopen cascade (PRD §3.9 three links).

    Link 1: CLOSED -> REOPENED, reopen_count += 1, closed_at cleared,
            resolution_timeliness -> NA.
    Link 2: FINDINGS_ACCEPTED investigation -> REOPENED; ISSUED letter -> SUPERSEDED.
    Link 3: dues re-anchored to now + 15 days in each variant; version += 1.
    """
    case["lifecycle_status"] = "REOPENED"
    case["reopen_count"] += 1
    case["closed_at"] = None
    case["resolution_timeliness"] = "NA"
    case["_closure_due_calendar_at"] = None
    for inv in db.investigations.values():
        if inv["case_id"] == case["id"] and inv["status"] == "FINDINGS_ACCEPTED":
            inv["status"] = "REOPENED"
            touch(inv)
    for letter in db.response_letters.values():
        if letter["case_id"] == case["id"] and letter["status"] == "ISSUED":
            letter["status"] = "SUPERSEDED"
            touch(letter)
    derived.anchor_dues(case, now, 15)
    touch(case)


def systemic_issue_sweep(case, now):
    """Auto-SYSTEMIC escalation after a GRIEVANCE decision (§3.2).

    Counts GRIEVANCE cases on the same unit+category received within the
    preceding 30 days (this case included, WITHDRAWN excluded); at >= 3 with no
    open SYSTEMIC escalation on that unit+category, files one on this case.
    """
    window_start = now - timedelta(days=30)
    count = 0
    for other in db.patient_cases.values():
        if (
            other["unit_id"] == case["unit_id"]
            and other["grievance_category"] == case["grievance_category"]
            and other["classification"] == "GRIEVANCE"
            and other["lifecycle_status"] != "WITHDRAWN"
            and parse_iso(other["received_at"]) >= window_start
        ):
            count += 1
    if count < 3:
        return None
    unit_case_ids = {
        c["id"]
        for c in db.patient_cases.values()
        if c["unit_id"] == case["unit_id"]
        and c["grievance_category"] == case["grievance_category"]
    }
    for e in db.escalations.values():
        if (
            e["case_id"] in unit_case_ids
            and e["escalation_type"] == "SYSTEMIC"
            and e["status"] in derived.OPEN_ESCALATION_STATUSES
        ):
            return None
    escalation = stamp_new()
    escalation.update(
        {
            "case_id": case["id"],
            "escalation_type": "SYSTEMIC",
            "source": "AUTO_SYSTEMIC_THRESHOLD",
            "status": "FILED",
            "review_track": None,
            "compliance_review_done": False,
            "safety_review_done": False,
            "filed_by_id": "system",
            "adjudicated_by_id": None,
            "adjudicated_at": None,
            "outcome_note": None,
        }
    )
    db.escalations[escalation["id"]] = escalation
    return escalation


def expedite_on_substantiation(case, escalation, now):
    """Substantiated-adjudication cascade (PRD §3.6 three links).

    Link 2: pull the dues in to adjudicated_at + 7 days when earlier (per
    variant). Link 3: if the recomputed calendar due already lies in the past
    and the case is unresolved, auto-file a SUBSTANTIATED_CARE_CONCERN
    ReportableEvent (deadline adjudicated_at + 5 business days).
    """
    tolling = derived.tolling_credit_seconds(case["id"], now)
    cal_due, biz_due, _ = derived.response_dues(case, now)
    if cal_due is not None and now + timedelta(days=7) < cal_due:
        case["_cal_anchor"] = now.isoformat()
        case["_cal_days"] = 7
        case["_cal_offset"] = -tolling
    if biz_due is not None:
        new_biz_base = business_due(now, 7, derived.holiday_dates())
        if new_biz_base < biz_due:
            case["_biz_anchor"] = now.isoformat()
            case["_biz_days"] = 7
            case["_biz_offset"] = -tolling
    cal_due_after, _, _ = derived.response_dues(case, now)
    if (
        cal_due_after is not None
        and cal_due_after < now
        and case["lifecycle_status"] not in ("CLOSED", "WITHDRAWN")
    ):
        event = stamp_new()
        event.update(
            {
                "case_id": case["id"],
                "escalation_id": escalation["id"],
                "authority_code": None,
                "trigger_reason": "SUBSTANTIATED_CARE_CONCERN",
                "status": "PENDING_FILING",
                "filed_at": None,
                "late_filing": False,
            }
        )
        db.reportable_events[event["id"]] = event
        return event
    return None
