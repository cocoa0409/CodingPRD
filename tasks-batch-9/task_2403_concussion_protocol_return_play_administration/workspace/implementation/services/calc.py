"""Derived quantities (PRD §2.8-§2.11, §3.2, §3.5, §3.6, §3.9, §3.10)."""
from datetime import timedelta
from fractions import Fraction

import constants as C
from db import db, sort_rows


# ------------------------------------------------------------------- rounding
def round_half_up(value):
    """Exact half-up rounding of a Fraction/int to a whole number."""
    frac = Fraction(value)
    num, den = frac.numerator, frac.denominator
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def hours(n):
    return timedelta(hours=n)


# --------------------------------------------------------------- row selectors
def player_cases(player_id):
    return sort_rows([c for c in db.concussion_cases.values() if c["player_id"] == player_id])


def club_cases(club_id):
    return sort_rows([c for c in db.concussion_cases.values() if c["club_id"] == club_id])


def club_audits(club_id):
    return sort_rows([a for a in db.protocol_audits.values() if a["club_id"] == club_id])


def case_steps(case_id):
    return sort_rows([s for s in db.return_steps.values() if s["case_id"] == case_id])


def case_clearances(case_id):
    return sort_rows([c for c in db.inc_clearances.values() if c["case_id"] == case_id])


def player_baselines(player_id):
    return sort_rows([b for b in db.baseline_tests.values() if b["player_id"] == player_id])


# ----------------------------------------------------------- baseline register
def latest_valid_baseline(player_id):
    candidates = [b for b in player_baselines(player_id) if b["status"] == "VALID"]
    if not candidates:
        return None
    return max(candidates, key=lambda b: (b["administered_at"], b["created_at"], b["_seq"]))


def resolve_baseline_status(player_id):
    """baseline_status_resolution. Returns the resolved enum value."""
    latest = latest_valid_baseline(player_id)
    if latest is None:
        return "NONE"
    if latest["retest_required_reason"] != "NONE":
        return "RETEST_REQUIRED"
    return "VALID"


# ------------------------------------------------------- public designation
def resolve_public_designation(player_id):
    cases = player_cases(player_id)
    if not cases:
        return "NONE"
    for case in cases:
        if case["case_status"] in (
            "MANDATORY_REMOVAL",
            "RTP_IN_PROGRESS",
            "PENDING_INC_CLEARANCE",
            "STAGE_FROZEN",
        ):
            return "OUT"
        if case["monitoring_status"] == "PROLONGED_SYMPTOM_WATCH":
            return "OUT"
    latest = max(cases, key=lambda c: (c["diagnosis_at"], c["created_at"], c["_seq"]))
    if latest["case_status"] == "CLEARED_FOR_CONTACT" and latest.get("cleared_for_contact_at"):
        window_end = latest["cleared_for_contact_at"] + hours(C.POST_CLEARANCE_QUESTIONABLE_HOURS)
        if db.now < window_end:
            if latest["recurrence_count"] >= 1:
                return "DOUBTFUL"
            return "QUESTIONABLE"
    return "NONE"


def diagnosed_case_count(player_id):
    return len(player_cases(player_id))


# --------------------------------------------------------------- case severity
def compute_severity_index(case):
    if case.get("_had_valid_baseline"):
        baseline_component = min(
            C.SEVERITY_BASELINE_CAP,
            round_half_up(Fraction(3, 2) * int(case.get("baseline_deviation_points") or 0)),
        )
    else:
        baseline_component = C.NO_BASELINE_PENALTY_POINTS
    symptom_component = min(
        C.SEVERITY_SYMPTOM_CAP,
        C.SEVERITY_SYMPTOM_POINTS_PER_UNIT * int(case["initial_symptom_score"]),
    )
    recurrence_component = min(
        C.SEVERITY_RECURRENCE_CAP,
        C.SEVERITY_RECURRENCE_POINTS_PER_UNIT * int(case["recurrence_count"]),
    )
    history_component = C.SEVERITY_PRIOR_CASE_POINTS if case.get("prior_case_id") else 0
    raw = (
        C.SEVERITY_BASE_POINTS
        + symptom_component
        + recurrence_component
        + baseline_component
        + history_component
    )
    return min(100, max(0, raw))


def provisional_projection(diagnosis_at, severity_index):
    total = C.BASE_RTP_HOURS
    if severity_index >= C.SEVERITY_HIGH_THRESHOLD:
        total += C.SEVERITY_SURCHARGE_HOURS
    return diagnosis_at + hours(total)


def final_accrued(stage5_evaluated_at, recurrence_count):
    return stage5_evaluated_at + hours(
        C.POST_STAGE5_REST_HOURS + C.RECURRENCE_PENALTY_HOURS * recurrence_count
    )


def days_since_diagnosis(case):
    delta = db.now - case["diagnosis_at"]
    seconds = delta.total_seconds()
    if seconds < 0:
        return 0
    return int(seconds // 86400)


def offseason_start_at(season_year):
    from datetime import datetime, timezone

    return datetime(season_year + 1, 2, 15, 0, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ rtp ladder
def passed_steps(case_id):
    return [s for s in case_steps(case_id) if s["status"] == "PASSED"]


def passed_stage_indexes(case_id):
    return set(s["stage_index"] for s in passed_steps(case_id))


def all_stages_passed(case_id):
    return passed_stage_indexes(case_id) >= set([1, 2, 3, 4, 5])


def documented_stage_count(case_id):
    return len(passed_stage_indexes(case_id))


def latest_passed_step(case_id):
    candidates = passed_steps(case_id)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda s: (s["stage_index"], s["attempt_index"], s["created_at"], s["_seq"]),
    )


def passed_step_for_stage(case_id, stage_index):
    candidates = [s for s in passed_steps(case_id) if s["stage_index"] == stage_index]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s["attempt_index"], s["created_at"], s["_seq"]))


def compute_min_start_at(case, stage_index):
    if stage_index <= 1:
        return case["diagnosis_at"]
    prev = passed_step_for_stage(case["id"], stage_index - 1)
    if prev is None or prev.get("evaluated_at") is None:
        return None
    return prev["evaluated_at"] + hours(C.STAGE_REST_HOURS[stage_index])


def compute_dwell_complete_at(started_at, stage_index):
    return started_at + hours(C.STAGE_MIN_HOURS[stage_index])


# ------------------------------------------------------------ exam block logic
def exam_block_conflict(inc_clinician_id, req_start, req_end, exclude_evaluation_id=None):
    for ev in sort_rows(list(db.sideline_evaluations.values())):
        if ev["id"] == exclude_evaluation_id:
            continue
        if ev.get("inc_clinician_id") != inc_clinician_id:
            continue
        if ev["status"] not in C.INC_BLOCK_HOLDING_STATUSES:
            continue
        start = ev.get("exam_started_at")
        end = ev.get("inc_block_ends_at")
        if start is None or end is None:
            continue
        if req_start <= end and start <= req_end:
            return True
    return False


def exam_duration_minutes(started_at, completed_at):
    seconds = (completed_at - started_at).total_seconds()
    if seconds < 0:
        return 0
    return int(seconds // 60)


# --------------------------------------------------------- compliance and fines
def _audit_weight(audit):
    return sum(C.VIOLATION_WEIGHT.get(code, 0) for code in audit.get("violation_codes") or [])


def compliance_score(club_id, included_statuses, exclude_audit_id=None):
    total = 0
    for audit in club_audits(club_id):
        if exclude_audit_id is not None and audit["id"] == exclude_audit_id:
            continue
        if audit["status"] in included_statuses:
            total += _audit_weight(audit)
    return max(0, 100 - total)


def preliminary_score(club_id, exclude_audit_id=None):
    return compliance_score(club_id, C.PRELIMINARY_INCLUDED_STATUSES, exclude_audit_id)


def adjudicated_score(club_id, exclude_audit_id=None):
    return compliance_score(club_id, C.ADJUDICATED_INCLUDED_STATUSES, exclude_audit_id)


def tier_for_score(score):
    if score >= 90:
        return "TIER_0"
    if score >= 75:
        return "TIER_1"
    if score >= 60:
        return "TIER_2"
    return "TIER_3"


def posture_for_score(score):
    if score >= 90:
        return "ACTIVE"
    if score >= 70:
        return "PROBATION"
    return "SANCTIONED"


def severity_factor_for_audit(audit):
    case_id = audit.get("case_id")
    if case_id:
        case = db.concussion_cases.get(case_id)
        if case and (case.get("severity_index") or 0) >= C.SEVERITY_HIGH_THRESHOLD:
            return Fraction(115, 100)
    return Fraction(1)


def compute_fine_cents(audit, tier):
    exposure_factor = Fraction(7 + int(audit.get("exposure_days") or 0), 7)
    severity_factor = severity_factor_for_audit(audit)
    codes = audit.get("violation_codes") or []
    gross = 0
    for code in C.VIOLATION_CODE_CANONICAL_ORDER:
        for _ in range(codes.count(code)):
            base = C.VIOLATION_BASE_CENTS[code]
            gross += round_half_up(Fraction(base) * exposure_factor * severity_factor)
    multiplier = {
        "TIER_0": Fraction(1),
        "TIER_1": Fraction(3, 2),
        "TIER_2": Fraction(2),
        "TIER_3": Fraction(3),
    }[tier]
    return round_half_up(Fraction(gross) * multiplier)


def outstanding_fine_cents(club_id, override_audit_id=None, override_value=None):
    total = 0
    for audit in club_audits(club_id):
        if audit["id"] == override_audit_id:
            if override_value is not None:
                total += override_value
            continue
        if audit["status"] in C.PRELIMINARY_INCLUDED_STATUSES:
            total += int(audit.get("assessed_fine_cents") or 0)
    return total


def open_violation_count(club_id):
    return sum(1 for a in club_audits(club_id) if a["status"] in C.OPEN_VIOLATION_STATUSES)


# -------------------------------------------------------------- slot ledger
def exemption_slots_used(club_id):
    return sum(1 for c in club_cases(club_id) if c["roster_exemption_status"] == "GRANTED")


def frozen_case_count(club_id):
    return sum(1 for c in club_cases(club_id) if c["case_status"] == "STAGE_FROZEN")
