"""Derived values, recomputed on every read from stored inputs (PRD §3.5).

Nothing derived is ever cached: business-day dues recompute against the current
holiday calendar, tolling credit re-merges suspension intervals against the
current clock, and regulatory_clock_status follows the pinned evaluation order
of the regulatory_clock_status_derivation calculation.
"""

import math
from datetime import timedelta

import db
from clock import business_due, parse_iso
from state import CLOCK

SEVERITY_BASE = {"STANDARD": 20, "URGENT": 35, "CRITICAL": 50}

OPEN_ESCALATION_STATUSES = {"FILED", "IN_REVIEW", "REVIEWS_COMPLETE"}


def holiday_dates():
    return {h["observance_date"] for h in db.holiday_observances.values()}


# ---------------------------------------------------------------------------
# Tolling credit (interval merge, SCAFFOLD §1.3 tolling_credit_seconds)
# ---------------------------------------------------------------------------


def case_suspensions(case_id):
    return [s for s in db.clock_suspensions.values() if s["case_id"] == case_id]


def has_open_suspension(case_id):
    return any(s["status"] == "OPEN" for s in case_suspensions(case_id))


def tolling_credit_seconds(case_id, now):
    """Interval-merged suspension credit in seconds (OPEN ends at now)."""
    intervals = []
    for s in case_suspensions(case_id):
        start = parse_iso(s["started_at"])
        end = parse_iso(s["closed_at"]) if s["status"] == "CLOSED" else now
        intervals.append((start, end))
    intervals.sort(key=lambda iv: iv[0])
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return int(sum((end - start).total_seconds() for start, end in merged))


# ---------------------------------------------------------------------------
# Regulatory dues (SCAFFOLD §1.3 regulatory_due_dates)
#
# Each case stores, per variant, an anchor instant, a day count, and a second
# offset (used by the expedite cascade, which pins the *due* to adjudicated_at
# + 7d by offsetting the anchor base by the then-current tolling credit).
# dues = variant_base(anchor, days) + offset + tolling_credit_seconds.
# ---------------------------------------------------------------------------


def response_dues(case, now=None):
    """Return (calendar_due, business_due, tolling_credit_seconds) as datetimes."""
    if now is None:
        now = CLOCK.now()
    tolling = tolling_credit_seconds(case["id"], now)
    cal_due = None
    biz_due = None
    if case.get("_cal_anchor"):
        cal_due = parse_iso(case["_cal_anchor"]) + timedelta(
            days=case["_cal_days"], seconds=case["_cal_offset"] + tolling
        )
    if case.get("_biz_anchor"):
        base = business_due(
            parse_iso(case["_biz_anchor"]), case["_biz_days"], holiday_dates()
        )
        biz_due = base + timedelta(seconds=case["_biz_offset"] + tolling)
    return cal_due, biz_due, tolling


def anchor_dues(case, anchor_dt, days):
    """Re-anchor both due variants to base = anchor + days (classification, reopen)."""
    case["_cal_anchor"] = anchor_dt.isoformat()
    case["_cal_days"] = days
    case["_cal_offset"] = 0
    case["_biz_anchor"] = anchor_dt.isoformat()
    case["_biz_days"] = days
    case["_biz_offset"] = 0


def grievance_window_days(case):
    """N per regulatory_due_dates: expedited 7 vs standard 30 vs complaint 3."""
    if case["classification"] == "GRIEVANCE":
        if case["severity_tier"] == "CRITICAL" or case["alleged_abuse_flag"]:
            return 7
        return 30
    if case["classification"] == "COMPLAINT":
        return 3
    return None


def recompute_dues_on_classification(case):
    """Recompute dues from received_at after any accepted decision."""
    n = grievance_window_days(case)
    if n is None:
        case["_cal_anchor"] = None
        case["_biz_anchor"] = None
        case["ack_due_at"] = None
        return
    from clock import iso_ms

    received = parse_iso(case["received_at"])
    anchor_dues(case, received, n)
    if case["classification"] == "GRIEVANCE":
        case["ack_due_at"] = iso_ms(received + timedelta(days=7))
    else:
        case["ack_due_at"] = None


# ---------------------------------------------------------------------------
# Regulatory clock status (pinned derivation order, PRD §3.5)
# ---------------------------------------------------------------------------


def regulatory_clock_status(case, now=None):
    if now is None:
        now = CLOCK.now()
    if case["lifecycle_status"] in ("CLOSED", "WITHDRAWN"):
        return "ON_TRACK"
    if case["classification"] == "UNCLASSIFIED":
        return "ON_TRACK"
    if has_open_suspension(case["id"]):
        return "SUSPENDED"
    cal_due, _, _ = response_dues(case, now)
    if cal_due is not None and now > cal_due:
        return "RESPONSE_BREACH"
    if (
        case["classification"] == "GRIEVANCE"
        and case["acknowledged_at"] is None
        and case["ack_due_at"] is not None
        and now > parse_iso(case["ack_due_at"])
    ):
        return "ACK_BREACH"
    return "ON_TRACK"


# ---------------------------------------------------------------------------
# Priority score (SCAFFOLD §1.3 case_priority_score)
# ---------------------------------------------------------------------------


def days_remaining(case, now=None):
    if now is None:
        now = CLOCK.now()
    cal_due, _, _ = response_dues(case, now)
    if cal_due is None:
        return None
    return math.floor((cal_due - now).total_seconds() / 86400)


def priority_score(case, now=None):
    if now is None:
        now = CLOCK.now()
    cal_due, _, _ = response_dues(case, now)
    base = SEVERITY_BASE[case["severity_tier"]]
    vulnerability = 15 if case["vulnerable_patient_flag"] else 0
    remaining = (
        math.floor((cal_due - now).total_seconds() / 86400)
        if cal_due is not None
        else 999
    )
    urgency = min(40, max(0, (10 - remaining) * 4))
    reopen_bonus = 10 * case["reopen_count"]
    return min(100, base + vulnerability + urgency + reopen_bonus)


# ---------------------------------------------------------------------------
# Other derived fields
# ---------------------------------------------------------------------------


def requires_qro_cosign(case):
    """True when severity CRITICAL or any ADJUDICATED_SUBSTANTIATED escalation."""
    if case["severity_tier"] == "CRITICAL":
        return True
    return any(
        e["case_id"] == case["id"] and e["status"] == "ADJUDICATED_SUBSTANTIATED"
        for e in db.escalations.values()
    )


def outstanding_recovery_cents(case_id):
    # PRD §3.8 operational ledger: issuance "raises ... by its value" and
    # revocation "falls by the action's value". A REVOKED action has left the
    # ISSUED set, so summing currently-ISSUED values reproduces exactly that
    # raise/fall netting (the catalog sentence's "minus REVOKED" clause read
    # literally would double-subtract and contradict both operational rules).
    total = 0
    for action in db.recovery_actions.values():
        if action["case_id"] != case_id:
            continue
        if action["status"] == "ISSUED":
            total += action["value_cents"]
    return total


def unit_open_case_count(unit_id):
    return sum(
        1
        for c in db.patient_cases.values()
        if c["unit_id"] == unit_id
        and c["lifecycle_status"] not in ("CLOSED", "WITHDRAWN")
    )


def unit_late_filed_event_count(unit_id):
    count = 0
    for event in db.reportable_events.values():
        if event["status"] != "LATE_FILED":
            continue
        case = db.patient_cases.get(event["case_id"])
        if case is not None and case["unit_id"] == unit_id:
            count += 1
    return count


def staff_open_assignment_count(staff_id):
    return sum(
        1
        for a in db.case_assignments.values()
        if a["investigator_id"] == staff_id and a["status"] == "ACTIVE"
    )


def investigation_note_counts(investigation_id):
    total = 0
    interviews = 0
    for note in db.investigation_notes.values():
        if note["investigation_id"] == investigation_id:
            total += 1
            if note["note_type"] == "INTERVIEW":
                interviews += 1
    return total, interviews


def active_primary_assignment(case_id):
    for a in db.case_assignments.values():
        if (
            a["case_id"] == case_id
            and a["status"] == "ACTIVE"
            and a["assignment_role"] == "PRIMARY"
        ):
            return a
    return None


def followup_due_at(followup):
    return business_due(parse_iso(followup["_base_closed_at"]), 5, holiday_dates())


def followup_expires_at(followup):
    due = followup_due_at(followup)
    return business_due(due, 10, holiday_dates())


def followup_status(followup, now=None):
    """PENDING past expires_at reads EXPIRED (derived, PRD §3.9)."""
    if followup["status"] != "PENDING":
        return followup["status"]
    if now is None:
        now = CLOCK.now()
    if now > followup_expires_at(followup):
        return "EXPIRED"
    return "PENDING"


def event_filing_deadline(event):
    """ALLEGED_ABUSE: created_at + 48h exact; otherwise +5 business days."""
    created = parse_iso(event["created_at"])
    if event["trigger_reason"] == "ALLEGED_ABUSE":
        return created + timedelta(hours=48)
    return business_due(created, 5, holiday_dates())
