"""Derived-field resolution, state transitions and cascades."""

from datetime import date, timedelta
from decimal import Decimal

import calc
from store import base_record, date_str, db, iso, now, sort_key, today, touch

OPEN_ASSESSMENT_STATUSES = calc.OPEN_ASSESSMENT_STATUSES
CLOSED_COMPLIANCE_STATUSES = calc.CLOSED_COMPLIANCE_STATUSES


# ---------------------------------------------------------------------------
# statutory clock (PRD §2.6, pinned seven-step resolution)
# ---------------------------------------------------------------------------

def approved_exclusions(evaluation_id):
    rows = [
        x for x in db.exclusions.values()
        if x["evaluation_id"] == evaluation_id and x["status"] == "APPROVED"
    ]
    return sorted(rows, key=sort_key)


def base_due_date_of(evaluation):
    start = date.fromisoformat(evaluation["clock_start_date"])
    return start + timedelta(days=calc.STATUTORY_EVAL_DAYS)


def resolve_clock(evaluation):
    """The seven pinned steps. Steps 1-6 only; step 7 is written by system actors."""
    frozen = evaluation.get("_frozen_clock")
    if frozen is not None:
        return dict(frozen)

    start = date.fromisoformat(evaluation["clock_start_date"])
    base_due = start + timedelta(days=calc.STATUTORY_EVAL_DAYS)          # step 1
    credited_sum = sum(x["days_credited"] for x in approved_exclusions(evaluation["id"]))  # step 2/3
    credited = min(credited_sum, calc.EXCLUSION_AGGREGATE_CAP_DAYS)     # step 3
    statutory_due = base_due + timedelta(days=credited)                 # step 4
    elapsed = max(0, calc.days_between(start, today()) - credited)      # step 5
    remaining = calc.STATUTORY_EVAL_DAYS - elapsed                      # step 6
    return {
        "base_due_date": date_str(base_due),
        "credited_exclusion_days": credited,
        "statutory_due_date": date_str(statutory_due),
        "elapsed_statutory_days": elapsed,
        "days_remaining": remaining,
    }


def freeze_clock(evaluation):
    """Closing a compliance posture freezes the stored day counts (PRD §2.6)."""
    if evaluation.get("_frozen_clock") is None:
        evaluation["_frozen_clock"] = resolve_clock(evaluation)


def days_remaining_of(evaluation):
    return resolve_clock(evaluation)["days_remaining"]


def exclusion_day_credit(exclusion, evaluation):
    """PRD §3.7 — intersect with the closed BASE window, then apply the type cap."""
    start = date.fromisoformat(evaluation["clock_start_date"])
    base_due = base_due_date_of(evaluation)
    claim_start = date.fromisoformat(exclusion["start_date"])
    claim_end = date.fromisoformat(exclusion["end_date"])
    overlap_start = max(claim_start, start)
    overlap_end = min(claim_end, base_due)
    if overlap_end < overlap_start:
        overlap_days = 0
    else:
        overlap_days = (overlap_end - overlap_start).days + 1
    return min(overlap_days, calc.PER_TYPE_CAP_DAYS[exclusion["exclusion_type"]])


# ---------------------------------------------------------------------------
# caseload aggregates (PRD §3.1)
# ---------------------------------------------------------------------------

def open_evaluations_of(psychologist_id):
    return [
        e for e in db.evaluations.values()
        if e["psychologist_id"] == psychologist_id
        and e["assessment_status"] in OPEN_ASSESSMENT_STATUSES
    ]


def apply_caseload(psychologist):
    """Full re-sweep of the source rows; returns True when a stored value moved."""
    rows = open_evaluations_of(psychologist["id"])
    points = sum(e["caseload_points"] for e in rows)
    capacity = psychologist["weekly_capacity_points"]
    if points < capacity:
        status = "BALANCED"
    elif points == capacity:
        status = "AT_CAP"
    else:
        status = "OVER_CAP"

    assigned_basis = calc.round_half_up(Decimal(points) / Decimal(capacity), 2)
    weighted_total = sum(
        (Decimal(e["caseload_points"]) * calc.urgency_weight(e["compliance_status"])
         for e in rows),
        Decimal(0),
    )
    clock_weighted = calc.round_half_up(weighted_total / Decimal(capacity), 2)

    changed = (
        psychologist["open_case_points"] != points
        or psychologist["caseload_status"] != status
        or psychologist["pressure_index_assigned_basis"] != assigned_basis
        or psychologist["pressure_index_clock_weighted"] != clock_weighted
    )
    psychologist["open_case_points"] = points
    psychologist["caseload_status"] = status
    psychologist["pressure_index_assigned_basis"] = assigned_basis
    psychologist["pressure_index_clock_weighted"] = clock_weighted
    return changed


def recompute_psychologist(psychologist_id):
    if not psychologist_id:
        return
    psychologist = db.psychologists.get(psychologist_id)
    if psychologist is None:
        return
    if apply_caseload(psychologist):
        touch(psychologist)


# ---------------------------------------------------------------------------
# assignment selector (PRD §3.3)
# ---------------------------------------------------------------------------

def select_psychologist(evaluation, referral):
    candidates = []
    for p in db.psychologists.values():
        if p["status"] != "ACTIVE":
            continue
        if referral["school_id"] not in p["assigned_school_ids"]:
            continue
        if referral["bilingual_evaluation_required"] and \
                referral["primary_language"] not in p["languages_certified"]:
            continue
        if p["credential_type"] not in ("SSP", "PHD") and \
                evaluation["referral_type"] != "REEVALUATION":
            continue
        if p["open_case_points"] + evaluation["caseload_points"] > p["weekly_capacity_points"]:
            continue
        candidates.append(p)

    if not candidates:
        return None

    ranked = []
    for p in candidates:
        rows = open_evaluations_of(p["id"])
        breached = sum(1 for e in rows if e["compliance_status"] == "BREACHED")
        same_school = 0
        for e in rows:
            ref = db.referrals.get(e["referral_id"])
            if ref is not None and ref["school_id"] == referral["school_id"]:
                same_school += 1
        score = calc.round_half_up(
            p["pressure_index_clock_weighted"]
            + calc.BREACH_PENALTY * max(0, breached - 1)
            - calc.CONTINUITY_BONUS * min(calc.CONTINUITY_CAP, same_school),
            2,
        )
        ranked.append((score, p["open_case_points"], p["created_at"], p["_seq"], p))

    ranked.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return ranked[0][4]


# ---------------------------------------------------------------------------
# evaluation creation (consent event cascade)
# ---------------------------------------------------------------------------

def create_evaluation(referral, effective_at):
    record = base_record()
    record.update({
        "referral_id": referral["id"],
        "psychologist_id": None,
        "prior_evaluation_id": referral["prior_evaluation_id"],
        "testing_instrument_id": None,
        "report_drafted_by_psychologist_id": None,
        "evaluation_domains": list(referral["requested_domains"]),
        "interpreter_required": referral["interpreter_required"],
        "referral_type": referral["referral_type"],
        "assessment_status": "PENDING_ASSIGNMENT",
        "compliance_status": "ON_TRACK",
        "clock_start_date": date_str(effective_at.date()),
        "caseload_points": calc.caseload_points(
            referral["requested_domains"],
            referral["interpreter_required"],
            referral["referral_type"],
        ),
        "reassignment_count": 0,
        "protocol_units_consumed": 0,
        "score_summary": None,
        "report_narrative": None,
        "_frozen_clock": None,
    })
    db.evaluations[record["id"]] = record
    return record


# ---------------------------------------------------------------------------
# cascade helpers
# ---------------------------------------------------------------------------

def cancel_scheduled_sessions(evaluation_id, reason):
    count = 0
    for session in sorted(db.sessions.values(), key=sort_key):
        if session["evaluation_id"] == evaluation_id and session["status"] == "SCHEDULED":
            session["status"] = "CANCELLED"
            session["cancellation_reason"] = reason
            touch(session)
            count += 1
    return count


def vacate_open_breaches(evaluation_id):
    for breach in sorted(db.breaches.values(), key=sort_key):
        if breach["evaluation_id"] == evaluation_id and \
                breach["status"] in ("DETECTED", "REMEDY_PROPOSED"):
            breach["status"] = "VACATED"
            breach["remedy_minutes_awarded"] = 0
            touch(breach)


def cancel_open_meetings(evaluation_id):
    for meeting in sorted(db.meetings.values(), key=sort_key):
        if meeting["evaluation_id"] == evaluation_id and \
                meeting["status"] in ("PROPOSED", "NOTICED", "RESCHEDULE_REQUESTED"):
            meeting["status"] = "CANCELLED"
            touch(meeting)


def withdraw_consent_cascade(referral):
    """PRD §3.2 Withdrawal — the identical four-part cascade."""
    evaluation_id = referral["active_evaluation_id"]
    if not evaluation_id:
        return
    evaluation = db.evaluations.get(evaluation_id)
    if evaluation is None:
        return

    prior_psychologist_id = evaluation["psychologist_id"]
    changed = False
    if evaluation["assessment_status"] not in ("REPORT_FINAL", "CANCELLED"):
        evaluation["assessment_status"] = "CANCELLED"
        changed = True
    if evaluation["compliance_status"] not in CLOSED_COMPLIANCE_STATUSES:
        freeze_clock(evaluation)
        evaluation["compliance_status"] = "WAIVED"
        changed = True
    if changed:
        touch(evaluation)

    cancel_scheduled_sessions(evaluation["id"], "CONSENT_WITHDRAWN")
    cancel_open_meetings(evaluation["id"])
    vacate_open_breaches(evaluation["id"])
    recompute_psychologist(prior_psychologist_id)


def leave_cascade(psychologist):
    """PRD §3.1 Staffing disruption — the deepest cascade in the product."""
    psychologist["status"] = "ON_LEAVE"
    for evaluation in sorted(db.evaluations.values(), key=sort_key):
        if evaluation["psychologist_id"] != psychologist["id"]:
            continue
        if evaluation["assessment_status"] not in OPEN_ASSESSMENT_STATUSES:
            continue
        evaluation["assessment_status"] = "PENDING_ASSIGNMENT"
        evaluation["psychologist_id"] = None
        evaluation["reassignment_count"] += 1
        touch(evaluation)
        cancel_scheduled_sessions(evaluation["id"], "PSYCHOLOGIST_UNAVAILABLE")
    apply_caseload(psychologist)
    touch(psychologist)


def create_breach(evaluation, days_remaining):
    breach_days = -days_remaining
    severity, day_basis, missed_basis = calc.compensatory_minutes(breach_days)
    record = base_record()
    record.update({
        "evaluation_id": evaluation["id"],
        "detected_at": iso(now()),
        "breach_days": breach_days,
        "severity": severity,
        "minutes_breach_day_basis": day_basis,
        "minutes_missed_service_basis": missed_basis,
        "remedy_basis": None,
        "additional_minutes": 0,
        "remedy_minutes_awarded": 0,
        "corrective_action_note": None,
        "proposed_by_user_id": None,
        "approved_by_user_id": None,
        "status": "DETECTED",
    })
    db.breaches[record["id"]] = record
    return record


def has_live_breach(evaluation_id):
    return any(
        b["evaluation_id"] == evaluation_id
        and b["status"] in ("DETECTED", "REMEDY_PROPOSED", "REMEDY_APPROVED")
        for b in db.breaches.values()
    )


# ---------------------------------------------------------------------------
# licence seats and instrument derivations
# ---------------------------------------------------------------------------

def assigned_seat_count(instrument_id):
    return sum(
        1 for s in db.seats.values()
        if s["instrument_id"] == instrument_id and s["status"] == "ASSIGNED"
    )


def license_seats_free(instrument):
    return instrument["license_seat_total"] - assigned_seat_count(instrument["id"])


def license_status(instrument):
    expires = date.fromisoformat(instrument["license_expires_on"])
    return "ACTIVE" if today() <= expires else "EXPIRED"


# ---------------------------------------------------------------------------
# scheduling helpers
# ---------------------------------------------------------------------------

def school_of_evaluation(evaluation):
    referral = db.referrals.get(evaluation["referral_id"])
    return None if referral is None else referral["school_id"]


def calendar_conflict(new_evaluation, start_at, end_at, exclude_session_id=None):
    """PRD §3.5 — half-open intervals plus a cross-building travel buffer."""
    psychologist_id = new_evaluation["psychologist_id"]
    if not psychologist_id:
        return False
    new_school = school_of_evaluation(new_evaluation)
    for session in db.sessions.values():
        if session["id"] == exclude_session_id:
            continue
        if session["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_evaluation = db.evaluations.get(session["evaluation_id"])
        if other_evaluation is None or other_evaluation["psychologist_id"] != psychologist_id:
            continue
        other_school = school_of_evaluation(other_evaluation)
        buffer = timedelta(minutes=0) if other_school == new_school \
            else timedelta(minutes=calc.TRAVEL_BUFFER_MINUTES)
        window_start = start_at - buffer
        window_end = end_at + buffer
        other_start = session["_start_at"]
        other_end = session["_end_at"]
        if window_start < other_end and other_start < window_end:
            return True
    return False


def meeting_capacity_blocked(school, start_at, end_at, exclude_meeting_ids):
    """PRD §3.8 — closed intervals, touching endpoints DO conflict."""
    count = 0
    for meeting in db.meetings.values():
        if meeting["id"] in exclude_meeting_ids:
            continue
        if meeting["school_id"] != school["id"]:
            continue
        if meeting["status"] not in ("PROPOSED", "NOTICED", "RESCHEDULE_REQUESTED", "HELD"):
            continue
        if start_at <= meeting["_end_at"] and meeting["_start_at"] <= end_at:
            count += 1
    return count >= school["concurrent_meeting_capacity"]
