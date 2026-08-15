"""Core domain logic: calculations, state transitions, cascades.

All business rules per PRD §3 and scaffold §1.2-§1.3.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RISK_BAND_VIOLATION,
    ERR_BOOKING_SUSPENDED,
    ERR_SESSION_LIMIT_REACHED,
    ERR_COUNSELOR_OVER_CAPACITY,
    ERR_TEMPORAL_INVALID,
    ERR_SCHEDULE_CONFLICT,
    ERR_NO_CRISIS_COVERAGE,
    ERR_POLICY_CONFLICT,
    ERR_REFERRAL_LOOP_EXHAUSTED,
    ERR_ENGAGEMENT_WINDOW,
)


# ---------------------------------------------------------------------------
# Constants (per scaffold §1.3)
# ---------------------------------------------------------------------------

ATTEMPT_MULTIPLIER = 3
IDEATION_BONUS = 15
MAX_POINTS = 100
CRITICAL_MIN = 60
HIGH_MIN = 35
MODERATE_MIN = 15

MIN_LIMIT = 2
DEFAULT_INTERSESSION_BASE = 6
EXEMPTION_BONUS_SESSIONS = 4

RATE_PER_MINUTE = 250
LATE_CANCEL_FEE_CENTS = 5000
NO_SHOW_FEE_CENTS = 7500
INSURANCE_CENTER_SHARE = Decimal("0.80")
SPLIT_CENTER_SHARE = Decimal("0.50")

WEEKS_IN_TERM = 15
ENGAGEMENT_CONFIRM_DAYS = 14
REFERRAL_LAPSE_DAYS = 30

RISK_BANDS = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
GROUP_RISK_CEILINGS = {"LOW", "MODERATE", "HIGH"}

# Band rank for "exceeds ceiling" comparisons.
BAND_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}


# ---------------------------------------------------------------------------
# intake_risk_score (scaffold §1.3)
# ---------------------------------------------------------------------------

def compute_risk(phq9: int, gad7: int, ideation_flag: bool, recent_attempt_flag: bool) -> tuple[int, str]:
    """Screening variant (default, persisted)."""
    base = phq9 + gad7
    if recent_attempt_flag:
        base = base * ATTEMPT_MULTIPLIER
    elif ideation_flag:
        base = base + IDEATION_BONUS
    points = min(MAX_POINTS, max(0, base))
    return points, band_for_points(points)


def band_for_points(points: int) -> str:
    if points >= CRITICAL_MIN:
        return "CRITICAL"
    if points >= HIGH_MIN:
        return "HIGH"
    if points >= MODERATE_MIN:
        return "MODERATE"
    return "LOW"


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_student(student_id: str) -> dict:
    s = db.students.get(student_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Student id does not exist")
    return s


def get_counselor(counselor_id: str) -> dict:
    c = db.counselors.get(counselor_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "Counselor id does not exist")
    return c


def get_assessment(assessment_id: str) -> dict:
    a = db.intake_assessments.get(assessment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "IntakeAssessment id does not exist")
    return a


def get_episode(episode_id: str) -> dict:
    e = db.episodes.get(episode_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, "CareEpisode id does not exist")
    return e


def get_session(session_id: str) -> dict:
    s = db.sessions.get(session_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "Session id does not exist")
    return s


def get_program(program_id: str) -> dict:
    p = db.group_programs.get(program_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "GroupProgram id does not exist")
    return p


def get_enrollment(enrollment_id: str) -> dict:
    e = db.group_enrollments.get(enrollment_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, "GroupEnrollment id does not exist")
    return e


def get_shift(shift_id: str) -> dict:
    s = db.crisis_shifts.get(shift_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "CrisisShift id does not exist")
    return s


def get_visit(visit_id: str) -> dict:
    v = db.crisis_visits.get(visit_id)
    if v is None:
        raise_err(ERR_NOT_FOUND, "CrisisVisit id does not exist")
    return v


def get_referral(referral_id: str) -> dict:
    r = db.referrals.get(referral_id)
    if r is None:
        raise_err(ERR_NOT_FOUND, "CommunityReferral id does not exist")
    return r


def get_policy(policy_id: str) -> dict:
    p = db.policies.get(policy_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "SemesterPolicy id does not exist")
    return p


def get_note(note_id: str) -> dict:
    n = db.clinical_notes.get(note_id)
    if n is None:
        raise_err(ERR_NOT_FOUND, "ClinicalNote id does not exist")
    return n


def get_outcome(outcome_id: str) -> dict:
    o = db.outcome_measures.get(outcome_id)
    if o is None:
        raise_err(ERR_NOT_FOUND, "OutcomeMeasure id does not exist")
    return o


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def published_policy_for_term(term: str | None) -> dict | None:
    """Return the PUBLISHED SemesterPolicy for the given term, or None."""
    if term is None:
        return None
    for p in db.policies.values():
        if p.get("academic_term") == term and p.get("policy_status") == "PUBLISHED":
            return p
    return None


def any_published_policy() -> dict | None:
    """Return the most recently created PUBLISHED policy (any term), or None."""
    published = [p for p in db.policies.values() if p.get("policy_status") == "PUBLISHED"]
    if not published:
        return None
    # most recently created
    published.sort(key=lambda p: (p.get("created_at", ""), p.get("id", "")))
    return published[-1]


# ---------------------------------------------------------------------------
# session_limit_for_episode (scaffold §1.3)
# ---------------------------------------------------------------------------

def session_limit_for_episode(risk_band: str, funding_model: str, academic_term: str) -> int:
    """Compute the episode's session limit.

    In intersession (no published policy for the term), use DEFAULT_INTERSESSION_BASE.
    """
    policy = published_policy_for_term(academic_term)
    if policy is not None:
        base = int(policy["base_session_limit"])
    else:
        base = DEFAULT_INTERSESSION_BASE

    if risk_band == "LOW":
        tier = base - 2
    elif risk_band == "MODERATE":
        tier = base
    elif risk_band == "HIGH":
        tier = base + 4
    elif risk_band == "CRITICAL":
        tier = base + 8
    else:
        tier = base

    if funding_model == "STUDENT_FEE":
        adj = 0
    elif funding_model == "INSURANCE":
        adj = -1
    elif funding_model == "SPLIT":
        adj = 1
    else:
        adj = 0

    limit = tier + adj
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    return limit


# ---------------------------------------------------------------------------
# session_billing_amount (scaffold §1.3)
# ---------------------------------------------------------------------------

def session_billing_amount(funding_model: str, event: str, duration_minutes: int) -> int:
    """Compute billed_amount_cents for a transitioning session.

    event in {"COMPLETED", "CANCELLED_LATE", "NO_SHOW_CHARGED"}.
    STUDENT_FEE: always 0. INSURANCE/SPLIT: gross * share rounded half-up once.
    """
    if funding_model == "STUDENT_FEE":
        return 0
    if event == "COMPLETED":
        gross = RATE_PER_MINUTE * int(duration_minutes)
    elif event == "CANCELLED_LATE":
        gross = LATE_CANCEL_FEE_CENTS
    elif event == "NO_SHOW_CHARGED":
        gross = NO_SHOW_FEE_CENTS
    else:
        gross = 0

    if funding_model == "INSURANCE":
        share = INSURANCE_CENTER_SHARE
    elif funding_model == "SPLIT":
        share = SPLIT_CENTER_SHARE
    else:
        share = Decimal("0")
    billed = (Decimal(gross) * share).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(billed)


# ---------------------------------------------------------------------------
# session_consumption_ledger (scaffold §1.3)
# ---------------------------------------------------------------------------

def recount_episode_consumption(episode: dict) -> int:
    """Full recount: count of linked sessions in {COMPLETED, NO_SHOW_CHARGED}."""
    count = 0
    for s in db.sessions.values():
        if s.get("episode_id") == episode["id"] and s.get("status") in ("COMPLETED", "NO_SHOW_CHARGED"):
            count += 1
    return count


def recompute_episode_after_consumption_change(episode: dict) -> None:
    """Recount consumption; refresh updated_at/version; fire exhaustion cascade
    if the recount crossed the limit and episode is OPEN with no exemption;
    handle excuse-driven EXHAUSTED->OPEN return.
    """
    new_count = recount_episode_consumption(episode)
    old_count = episode.get("sessions_consumed", 0)
    if new_count != old_count:
        episode["sessions_consumed"] = new_count
        db.touch(episode)

    # Exhaustion cascade (OPEN -> EXHAUSTED) when recount reaches limit.
    if (
        episode.get("status") == "OPEN"
        and not episode.get("exemption_granted", False)
        and episode.get("sessions_consumed", 0) >= episode.get("session_limit", 0)
    ):
        episode["status"] = "EXHAUSTED"
        db.touch(episode)
        # Create exhaustion referral
        _create_exhaustion_referral(episode)
        # Cancel remaining SCHEDULED sessions
        _cancel_episode_scheduled_sessions(episode, "EPISODE_EXHAUSTED")

    # Excuse-driven return: EXHAUSTED -> OPEN when consumption falls below limit
    # and no linked referral has been ACCEPTED.
    if (
        episode.get("status") == "EXHAUSTED"
        and episode.get("sessions_consumed", 0) < episode.get("session_limit", 0)
    ):
        # Check for an ACCEPTED referral linked to this episode.
        has_accepted_referral = any(
            r.get("episode_id") == episode["id"] and r.get("status") == "ACCEPTED"
            for r in db.referrals.values()
        )
        if not has_accepted_referral:
            episode["status"] = "OPEN"
            db.touch(episode)


def _create_exhaustion_referral(episode: dict) -> None:
    referral = {
        "student_id": episode["student_id"],
        "episode_id": episode["id"],
        "provider_name": None,
        "required_specialty": "GEN",
        "status": "PENDING",
        "rematch_count": 0,
    }
    db.stamp_new(referral)
    db.referrals[referral["id"]] = referral


def _cancel_episode_scheduled_sessions(episode: dict, reason: str) -> None:
    """Cancel every SCHEDULED session on this episode (timely, with reason)."""
    for s in db.sessions.values():
        if s.get("episode_id") == episode["id"] and s.get("status") == "SCHEDULED":
            s["status"] = "CANCELLED_TIMELY"
            s["cancellation_reason"] = reason
            db.touch(s)


# ---------------------------------------------------------------------------
# no_show_strike_total (scaffold §1.3)
# ---------------------------------------------------------------------------

def current_term_for_student(student_id: str) -> str | None:
    """current_term = academic_term of student's most recently created
    non-terminal CareEpisode. Terminal episode states: CLOSED, REFERRED_OUT,
    REOPENED. Non-terminal: OPEN, EXHAUSTED."""
    non_terminal = [
        e for e in db.episodes.values()
        if e.get("student_id") == student_id and e.get("status") in ("OPEN", "EXHAUSTED")
    ]
    if not non_terminal:
        return None
    non_terminal.sort(key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    return non_terminal[-1].get("academic_term")


def recompute_student_strikes(student: dict) -> int:
    """Recount chargeable no-show strikes scoped to current term and anchor."""
    term = current_term_for_student(student["id"])
    if term is None:
        count = 0
    else:
        anchor_str = student.get("strike_reset_anchor") or "1970-01-01T00:00:00Z"
        anchor_dt = db.parse_iso(anchor_str)
        count = 0
        for s in db.sessions.values():
            if s.get("status") != "NO_SHOW_CHARGED":
                continue
            ep = db.episodes.get(s.get("episode_id"))
            if ep is None:
                continue
            if ep.get("student_id") != student["id"]:
                continue
            if ep.get("academic_term") != term:
                continue
            upd_str = s.get("updated_at") or s.get("created_at")
            if upd_str is None:
                continue
            upd_dt = db.parse_iso(upd_str)
            if upd_dt > anchor_dt:
                count += 1
    if student.get("no_show_strike_count") != count:
        student["no_show_strike_count"] = count
        db.touch(student)
    return count


def recompute_booking_posture(student: dict) -> None:
    """Recompute student.booking_posture under the published policy for the
    current term. Fires posture transitions and cascades per §1.2 Student."""
    old_posture = student.get("booking_posture", "CLEAR")
    term = current_term_for_student(student["id"])
    policy = published_policy_for_term(term) if term else None
    if policy is None:
        # No published policy for current term: no posture enforcement.
        return
    limit = int(policy.get("no_show_strike_limit", 1))
    count = int(student.get("no_show_strike_count", 0))

    new_posture = old_posture
    if old_posture == "CLEAR":
        if count >= limit:
            new_posture = "SUSPENDED"
        elif count == limit - 1:
            new_posture = "RESTRICTED"
    elif old_posture == "RESTRICTED":
        if count >= limit:
            new_posture = "SUSPENDED"
        elif count < limit - 1:
            new_posture = "CLEAR"
    elif old_posture == "SUSPENDED":
        # No automatic path from SUSPENDED back; only strikes/reset lifts it.
        new_posture = "SUSPENDED"

    if new_posture != old_posture:
        student["booking_posture"] = new_posture
        db.touch(student)
        if new_posture == "SUSPENDED":
            _cancel_future_sessions_for_suspension(student)


def _cancel_future_sessions_for_suspension(student: dict) -> None:
    """Cancel every SCHEDULED session for this student whose starts_at is
    strictly after the current logical clock; mark CANCELLED_TIMELY with
    reason POLICY_SUSPENSION."""
    now = db.clock()
    # Find episodes for student
    student_episode_ids = {
        e["id"] for e in db.episodes.values() if e.get("student_id") == student["id"]
    }
    for s in db.sessions.values():
        if s.get("episode_id") not in student_episode_ids:
            continue
        if s.get("status") != "SCHEDULED":
            continue
        starts_at_str = s.get("starts_at")
        if not starts_at_str:
            continue
        starts_dt = db.parse_iso(starts_at_str)
        if starts_dt > now:
            s["status"] = "CANCELLED_TIMELY"
            s["cancellation_reason"] = "POLICY_SUSPENSION"
            db.touch(s)


def recompute_strikes_and_posture(student: dict) -> None:
    recompute_student_strikes(student)
    recompute_booking_posture(student)


# ---------------------------------------------------------------------------
# counselor_caseload_load (scaffold §1.3)
# ---------------------------------------------------------------------------

def counselor_caseload_load(counselor_id: str) -> int:
    """Sum of CURRENT risk points over counselor's OPEN+EXHAUSTED episodes.

    Points are taken from each episode's linked intake assessment. Episodes
    created by crisis RETURN_TO_CARE have intake_assessment_id null; they
    contribute their stored _crisis_risk_points (computed from presenting band)
    if present, else 0.
    """
    total = 0
    for e in db.episodes.values():
        if e.get("primary_counselor_id") != counselor_id:
            continue
        if e.get("status") not in ("OPEN", "EXHAUSTED"):
            continue
        total += episode_risk_points(e)
    return total


def episode_risk_points(episode: dict) -> int:
    ia_id = episode.get("intake_assessment_id")
    if ia_id:
        a = db.intake_assessments.get(ia_id)
        if a is not None:
            return int(a.get("risk_points", 0))
    # Crisis-created episode: derive from stored band via session limit proxy.
    # We store _crisis_risk_points at creation time.
    return int(episode.get("_crisis_risk_points", 0))


def counselor_pending_session_count(counselor_id: str) -> int:
    """Count of counselor's sessions in {SCHEDULED, HELD}."""
    return sum(
        1
        for s in db.sessions.values()
        if s.get("counselor_id") == counselor_id and s.get("status") in ("SCHEDULED", "HELD")
    )


# ---------------------------------------------------------------------------
# Overlap checks (scaffold §1.4 p9)
# ---------------------------------------------------------------------------

def counselor_session_overlap(counselor_id: str, new_start: datetime, new_duration_min: int, exclude_session_id: str | None = None) -> bool:
    """True if new interval overlaps any existing SCHEDULED/HELD session of
    this counselor."""
    new_end = new_start + timedelta(minutes=new_duration_min)
    for s in db.sessions.values():
        if s.get("counselor_id") != counselor_id:
            continue
        if exclude_session_id and s.get("id") == exclude_session_id:
            continue
        if s.get("status") not in ("SCHEDULED", "HELD"):
            continue
        s_start_str = s.get("starts_at")
        if not s_start_str:
            continue
        s_start = db.parse_iso(s_start_str)
        s_end = s_start + timedelta(minutes=int(s.get("duration_minutes", 0)))
        # [start, end) overlap
        if new_start < s_end and s_start < new_end:
            return True
    return False


def counselor_shift_overlap(counselor_id: str, new_start: datetime, new_end: datetime, exclude_shift_id: str | None = None) -> bool:
    """True if the counselor already holds a CLAIMED shift overlapping
    [new_start, new_end)."""
    for sh in db.crisis_shifts.values():
        if sh.get("claimed_by_id") != counselor_id:
            continue
        if sh.get("status") != "CLAIMED":
            continue
        if exclude_shift_id and sh.get("id") == exclude_shift_id:
            continue
        s_start = db.parse_iso(sh["starts_at"])
        s_end = db.parse_iso(sh["ends_at"])
        if new_start < s_end and s_start < new_end:
            return True
    return False


# ---------------------------------------------------------------------------
# group_waitlist_order (scaffold §1.3)
# ---------------------------------------------------------------------------

def promote_waitlist_head(program: dict) -> None:
    """If enrolled count < capacity, promote the waitlist head.

    Tie-break: earliest created_at; then LOWER student.no_show_strike_count;
    then Student.created_at ASC. Never id.
    """
    enrolled_count = sum(
        1
        for e in db.group_enrollments.values()
        if e.get("program_id") == program["id"] and e.get("status") == "ENROLLED"
    )
    if enrolled_count >= int(program.get("capacity", 0)):
        return
    waitlisted = [
        e for e in db.group_enrollments.values()
        if e.get("program_id") == program["id"] and e.get("status") == "WAITLISTED"
    ]
    if not waitlisted:
        return

    def sort_key(enr):
        student = db.students.get(enr.get("student_id")) or {}
        return (
            enr.get("created_at", ""),
            int(student.get("no_show_strike_count", 0)),
            student.get("created_at", ""),
        )

    waitlisted.sort(key=sort_key)
    head = waitlisted[0]
    head["status"] = "ENROLLED"
    # GroupEnrollment has no version/updated_at per PRD §2.4 (light resource).


def remove_student_enrollments_for_risk(student_id: str) -> None:
    """Force-remove ENROLLED enrollments whose program ceiling is now exceeded
    (used on CRITICAL intake re-band and EMERGENCY_TRANSPORT disposition).

    For CRITICAL band, every enrollment is removed (CRITICAL students are never
    group-eligible). For EMERGENCY_TRANSPORT, the same rule applies per §1.2.
    """
    affected_programs = set()
    for enr in db.group_enrollments.values():
        if enr.get("student_id") != student_id:
            continue
        if enr.get("status") != "ENROLLED":
            continue
        enr["status"] = "REMOVED_RISK"
        affected_programs.add(enr.get("program_id"))
    for pid in affected_programs:
        program = db.group_programs.get(pid)
        if program is not None:
            promote_waitlist_head(program)


# ---------------------------------------------------------------------------
# Clock-driven auto-transitions (per PRD §2.5)
# ---------------------------------------------------------------------------

def apply_clock_transitions(new_dt: datetime) -> None:
    """On logical clock advance, evaluate all time-based auto-transitions."""
    # GroupProgram OPEN -> RUNNING (when start reached and >=1 ENROLLED)
    for prog in db.group_programs.values():
        if prog.get("status") == "OPEN":
            start = db.parse_iso(prog["starts_at"])
            if new_dt >= start:
                enrolled_count = sum(
                    1
                    for e in db.group_enrollments.values()
                    if e.get("program_id") == prog["id"] and e.get("status") == "ENROLLED"
                )
                if enrolled_count >= 1:
                    prog["status"] = "RUNNING"
                    db.touch(prog)

    # GroupProgram RUNNING -> COMPLETED (after starts_at + weeks*7 days)
    for prog in db.group_programs.values():
        if prog.get("status") == "RUNNING":
            start = db.parse_iso(prog["starts_at"])
            end = start + timedelta(days=int(prog.get("weeks", 0)) * 7)
            if new_dt >= end:
                prog["status"] = "COMPLETED"
                db.touch(prog)

    # CrisisShift CLAIMED -> COVERED (when ends_at passed)
    for shift in db.crisis_shifts.values():
        if shift.get("status") == "CLAIMED":
            end = db.parse_iso(shift["ends_at"])
            if new_dt >= end:
                shift["status"] = "COVERED"
                db.touch(shift)

    # CommunityReferral PENDING -> LAPSED (30 days since updated_at)
    for ref in db.referrals.values():
        if ref.get("status") == "PENDING":
            upd = db.parse_iso(ref["updated_at"])
            if new_dt >= upd + timedelta(days=REFERRAL_LAPSE_DAYS):
                ref["status"] = "LAPSED"
                db.touch(ref)


# ---------------------------------------------------------------------------
# Risk re-banding hook (new IntakeAssessment created)
# ---------------------------------------------------------------------------

def on_new_intake_assessment(student_id: str, assessment: dict) -> None:
    """A fresh intake re-bands the student. If the new band is CRITICAL, force
    group removal; counselor caseloads recompute dynamically (we always sum
    live), so no persistent caseload counter needs updating here."""
    if assessment.get("risk_band") == "CRITICAL":
        remove_student_enrollments_for_risk(student_id)
