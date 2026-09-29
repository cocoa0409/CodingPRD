"""Derived-field recomputation, posture gating and cascade helpers."""

from datetime import timedelta
from decimal import Decimal

import calcs
import db
import spec
from db import (add_days, all_of, clock_date, clock_now, days_between, fmt_date,
                mark, month_bounds, parse_date, parse_instant)


# ----------------------------------------------------------------- child views

def cases_of_program(program_id):
    return [c for c in all_of("case") if c["program_id"] == program_id]


def entries_of_source(source_id):
    return [e for e in all_of("entry") if e["source_id"] == source_id]


def deficiencies_of_program(program_id):
    return [d for d in all_of("deficiency") if d["program_id"] == program_id]


def submissions_of_program(program_id):
    return [s for s in all_of("submission") if s["program_id"] == program_id]


def sessions_of_program(program_id):
    return [s for s in all_of("session") if s["program_id"] == program_id]


def abstractions_of_case(case_id):
    return [a for a in all_of("abstraction") if a["case_id"] == case_id]


def items_of_submission(submission_id):
    return [i for i in all_of("item") if i["submission_id"] == submission_id]


def audits_of_abstraction(abstraction_id):
    return [a for a in all_of("audit") if a["abstraction_id"] == abstraction_id]


def open_deficiency_count(program_id, severities):
    return len([d for d in deficiencies_of_program(program_id)
                if d["severity"] in severities
                and d["deficiency_state"] in spec.OPEN_DEFICIENCY_STATES])


# ------------------------------------------------------------------ tumor case

def refresh_case_timeliness(case):
    mark(case)
    due = parse_date(case["abstract_due_date"])
    status, days = calcs.timeliness(case, due, clock_date())
    case["timeliness_status"] = status
    case["days_to_due"] = days


def refresh_case_follow_up(case):
    mark(case)
    if not case.get("analytic_flag"):
        case["follow_up_status"] = "NOT_REQUIRED"
        case["follow_up_due_date"] = None
        return
    if case.get("vital_status") == "DEAD":
        case["follow_up_status"] = "CLOSED_DECEASED"
        case["follow_up_due_date"] = None
        return
    anchor_raw = case.get("last_contact_date") or case.get("first_contact_date")
    anchor = parse_date(anchor_raw)
    due = add_days(anchor, spec.FOLLOW_UP_CURRENT_MAX_DAYS)
    case["follow_up_due_date"] = fmt_date(due)
    age = days_between(anchor, clock_date())
    if age <= spec.FOLLOW_UP_CURRENT_MAX_DAYS:
        case["follow_up_status"] = "CURRENT"
    elif age <= spec.FOLLOW_UP_DELINQUENT_MAX_DAYS:
        case["follow_up_status"] = "DELINQUENT"
    else:
        case["follow_up_status"] = "LOST"


# ------------------------------------------------------------ casefinding source

def refresh_source_completeness(source, write_reconciled_through=False):
    mark(source)
    first, last = month_bounds(clock_date())
    count = 0
    for entry in entries_of_source(source["id"]):
        accession = parse_date(entry["accession_date"])
        if accession is not None and first <= accession <= last:
            count += 1
    source["entries_this_month"] = count
    expected = source["expected_monthly_volume"]
    if expected == 0:
        source["casefinding_completeness_pct"] = 100.0
    else:
        ratio = Decimal(count) / Decimal(expected)
        if ratio > Decimal(1):
            ratio = Decimal(1)
        source["casefinding_completeness_pct"] = float(
            calcs.rhu(ratio * Decimal(100), 1))
    if write_reconciled_through:
        source["last_reconciled_through"] = fmt_date(clock_date())


# ---------------------------------------------------------------- follow-up rates

def compute_follow_up_rates(program_id):
    base = [c for c in cases_of_program(program_id)
            if c.get("analytic_flag") and c["case_state"] == "COMPLETED"]
    today = clock_date()

    den_coc = []
    for case in base:
        dx = parse_date(case["diagnosis_date"])
        if days_between(dx, today) > spec.COC_COHORT_MAX_DIAGNOSIS_AGE_DAYS:
            continue
        if case.get("vital_status") == "DEAD":
            continue
        den_coc.append(case)
    num_coc = []
    for case in den_coc:
        lcd = parse_date(case.get("last_contact_date"))
        if lcd is not None and days_between(lcd, today) <= spec.FOLLOW_UP_DELINQUENT_MAX_DAYS:
            num_coc.append(case)

    if not den_coc:
        coc_rate = 100.0
        lost_coc = 0.0
    else:
        coc_rate = calcs.pct(len(num_coc), len(den_coc))
        lost_coc = calcs.pct(len(den_coc) - len(num_coc), len(den_coc))

    den_state = list(base)
    num_state = []
    for case in den_state:
        if case.get("vital_status") == "DEAD":
            num_state.append(case)
            continue
        lcd = parse_date(case.get("last_contact_date"))
        if lcd is not None and days_between(lcd, today) <= spec.FOLLOW_UP_CURRENT_MAX_DAYS:
            num_state.append(case)
    state_rate = 100.0 if not den_state else calcs.pct(len(num_state),
                                                       len(den_state))
    return coc_rate, state_rate, lost_coc


def refresh_program_follow_up(program):
    mark(program)
    coc, state, lost = compute_follow_up_rates(program["id"])
    program["follow_up_rate_coc_pct"] = coc
    program["follow_up_rate_state_pct"] = state
    program["lost_to_follow_up_pct"] = lost


# ------------------------------------------------------------ conference compliance

def _window_bounds():
    today = clock_date()
    total = today.year * 12 + (today.month - 1) - 11
    year = total // 12
    month = total % 12 + 1
    from datetime import date as _date
    start = _date(year, month, 1)
    _, end = month_bounds(today)
    return start, end


def required_sessions_12mo(program):
    per_month = 2 if program["annual_analytic_caseload"] >= spec.HIGH_VOLUME_CASELOAD else 1
    return per_month * 12


def refresh_program_conference(program):
    mark(program)
    start, end = _window_bounds()
    credited = []
    for session in sessions_of_program(program["id"]):
        if session["session_state"] != "CREDITED":
            continue
        started = parse_instant(session["start_at"])
        if started is None:
            continue
        if start <= started.date() <= end:
            credited.append(session)
    program["required_sessions_12mo"] = required_sessions_12mo(program)
    program["credited_sessions_12mo"] = len(credited)
    program["conference_frequency_compliant"] = (
        len(credited) >= program["required_sessions_12mo"])

    coordinator_refs = []
    for session in credited:
        for att in session.get("attendances") or []:
            if att.get("is_required_coordinator") and att.get("attendee_ref") not in coordinator_refs:
                coordinator_refs.append(att.get("attendee_ref"))
    if not credited or not coordinator_refs:
        program["coordinator_attendance_compliant"] = False
        return
    compliant = True
    for ref in coordinator_refs:
        attended = 0
        for session in credited:
            for att in session.get("attendances") or []:
                if (att.get("attendee_ref") == ref
                        and (att.get("attended_minutes") or 0) >= spec.CONFERENCE_QUALIFYING_MINUTES):
                    attended += 1
                    break
        rate = calcs.pct(attended, len(credited))
        if Decimal(str(rate)) < Decimal(str(spec.COORDINATOR_ATTENDANCE_MIN_PCT)):
            compliant = False
    program["coordinator_attendance_compliant"] = compliant


# ------------------------------------------------------------------ posture

def _decide_posture(program):
    if program["accreditation_state"] in ("PROBATION", "WITHDRAWN"):
        return "FROZEN"
    if program["open_critical_deficiency_count"] >= 1:
        return "FROZEN"
    if program["overdue_backlog_count"] >= 2:
        return "FROZEN"
    if program["open_backlog_count"] >= 4:
        return "RESTRICTED"
    return "OPEN"


def _sweep_submissions(program, previous, current):
    if previous != "FROZEN" and current == "FROZEN":
        targets = [s for s in submissions_of_program(program["id"])
                   if s["submission_state"] == "DRAFT"]
        targets.sort(key=lambda s: (s["period_start"], s["created_at"], s["_seq"]))
        for sub in targets:
            mark(sub)
            sub["pre_hold_state"] = "DRAFT"
            sub["submission_state"] = "HOLD"
    elif previous == "FROZEN" and current != "FROZEN":
        targets = [s for s in submissions_of_program(program["id"])
                   if s["submission_state"] == "HOLD"]
        targets.sort(key=lambda s: (s["period_start"], s["created_at"], s["_seq"]))
        for sub in targets:
            mark(sub)
            sub["submission_state"] = sub.get("pre_hold_state") or "DRAFT"
            sub["pre_hold_state"] = None


def refresh_program_aggregates(program):
    """Refresh the three posture counts plus identified_case_count, then the
    posture, cascading into the submission workflow."""
    mark(program)
    cases = cases_of_program(program["id"])
    program["identified_case_count"] = len(
        [c for c in cases if c["case_state"] != "VOIDED"])
    open_cases = [c for c in cases if c["case_state"] in spec.OPEN_CASE_STATES]
    program["open_backlog_count"] = len(open_cases)
    program["overdue_backlog_count"] = len(
        [c for c in open_cases if c["timeliness_status"] == "LATE"])
    program["open_critical_deficiency_count"] = open_deficiency_count(
        program["id"], ("CRITICAL",))
    previous = program["registry_posture"]
    current = _decide_posture(program)
    program["registry_posture"] = current
    _sweep_submissions(program, previous, current)


# --------------------------------------------------------------- abstractor

def closed_audits_for_author(abstractor_id):
    result = []
    for audit in all_of("audit"):
        if audit["audit_state"] not in spec.CLOSED_AUDIT_STATES:
            continue
        abstraction = db.get("abstraction", audit["abstraction_id"])
        if abstraction is None:
            continue
        if abstraction.get("abstractor_id") != abstractor_id:
            continue
        result.append(audit)
    return result


def refresh_abstractor_quality(abstractor):
    mark(abstractor)
    cohort = closed_audits_for_author(abstractor["id"])
    cutoff = clock_now() - timedelta(days=spec.ROLLING_QUALITY_WINDOW_DAYS)

    rolling_fields = 0
    rolling_weighted = 0
    for audit in cohort:
        scored = parse_instant(audit.get("scored_at"))
        if scored is None or scored < cutoff:
            continue
        rolling_fields += audit["audited_field_count"]
        rolling_weighted += audit["weighted_error_score"]
    if rolling_fields == 0:
        abstractor["quality_score_rolling_90d"] = 100.0
    else:
        value = Decimal(100) - (Decimal(rolling_weighted) / Decimal(rolling_fields)
                               * Decimal(100))
        abstractor["quality_score_rolling_90d"] = calcs.clamp_pct(
            float(calcs.rhu(value, 1)))

    total_fields = 0
    total_discrepancies = 0
    for audit in cohort:
        total_fields += audit["audited_field_count"]
        total_discrepancies += (audit["minor_discrepancy_count"]
                                + audit["major_discrepancy_count"]
                                + audit["critical_discrepancy_count"])
    if total_fields == 0:
        abstractor["quality_score_cumulative"] = 100.0
    else:
        value = Decimal(100) - (Decimal(total_discrepancies) / Decimal(total_fields)
                               * Decimal(100))
        abstractor["quality_score_cumulative"] = calcs.clamp_pct(
            float(calcs.rhu(value, 1)))


def refresh_abstractor_productivity(abstractor):
    mark(abstractor)
    today = clock_date()
    count = 0
    for abstraction in all_of("abstraction"):
        if abstraction["abstractor_id"] != abstractor["id"]:
            continue
        if abstraction["abstraction_state"] != "APPROVED":
            continue
        approved = parse_instant(abstraction.get("approved_at"))
        if approved is None:
            continue
        age = days_between(approved.date(), today)
        if 0 <= age <= spec.PRODUCTIVITY_WINDOW_DAYS:
            count += 1
    abstractor["completed_cases_30d"] = count
    rate = calcs.productivity_rate(count)
    abstractor["productivity_rate_per_day"] = rate
    target = Decimal(str(abstractor["productivity_target_cases_per_day"]))
    abstractor["productivity_status"] = (
        "MEETS" if Decimal(str(rate)) >= target else "BELOW")


def recompute_fail_streak(abstractor):
    """Trailing run of consecutive non-PASS verdicts among closed audits."""
    cohort = closed_audits_for_author(abstractor["id"])
    cohort.sort(key=lambda a: (a.get("scored_at") or "", a["_seq"]))
    streak = 0
    for audit in reversed(cohort):
        if audit.get("verdict") == "PASS":
            break
        streak += 1
    return streak


def release_worklist(abstractor):
    """Return every open case of the registrar to IDENTIFIED (PRD 3.2)."""
    targets = [c for c in all_of("case")
               if c.get("assigned_abstractor_id") == abstractor["id"]
               and c["case_state"] in spec.ASSIGNED_OPEN_CASE_STATES]
    targets.sort(key=lambda c: (c["created_at"], c["_seq"]))
    programs = []
    for case in targets:
        mark(case)
        case["assigned_abstractor_id"] = None
        case["case_state"] = "IDENTIFIED"
        refresh_case_timeliness(case)
        for abstraction in abstractions_of_case(case["id"]):
            if abstraction["abstraction_state"] in ("DRAFT", "REWORK_REQUIRED"):
                mark(abstraction)
                abstraction["abstraction_state"] = "REJECTED"
        if case["program_id"] not in programs:
            programs.append(case["program_id"])
    mark(abstractor)
    abstractor["assigned_open_case_count"] = 0
    for program_id in programs:
        program = db.get("program", program_id)
        if program is not None:
            refresh_program_aggregates(program)


# ------------------------------------------------------------------ deficiency

def response_due_date(severity, cited_on):
    return add_days(cited_on, spec.RESPONSE_WINDOW_DAYS[severity])


def escalate_deficiency(deficiency):
    mark(deficiency)
    deficiency["escalation_count"] = deficiency["escalation_count"] + 1
    deficiency["deficiency_state"] = "ESCALATED"
    program = db.get("program", deficiency["program_id"])
    if program is None:
        return
    mark(program)
    if program["accreditation_state"] in ("ACCREDITED", "SURVEY_SCHEDULED",
                                          "DEFICIENCY_RESPONSE"):
        program["accreditation_state"] = "PROBATION"
    refresh_program_aggregates(program)


def cite_deficiency(program, standard_code, severity, cited_on,
                    evidence_reference=None, source_measure_id=None):
    """Create a CITED deficiency and apply the severity-driven posture effect."""
    deficiency = db.new_entity("deficiency", {
        "program_id": program["id"],
        "standard_code": standard_code,
        "severity": severity,
        "cited_on": fmt_date(cited_on),
        "response_due_date": fmt_date(response_due_date(severity, cited_on)),
        "deficiency_state": "CITED",
        "escalation_count": 0,
        "response_narrative": None,
        "evidence_reference": evidence_reference,
        "reviewer_notes": None,
        "source_measure_id": source_measure_id,
        "_responded_by_user_id": None,
    })
    if severity == "CRITICAL":
        refresh_program_aggregates(program)
    return deficiency
