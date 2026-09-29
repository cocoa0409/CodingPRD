"""Business logic: calculations, derived fields, cascades and state transitions.

All minute arithmetic uses `decimal.Decimal` with ROUND_HALF_UP (PRD §2.8) —
never binary floats and never Python's banker's-rounding `round()`.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import ApiError
from validation import parse_date, parse_datetime

# --------------------------------------------------------------------------
# constants (PRD §3.3, §3.5, §3.6, §3.7 / scaffold calculations)
# --------------------------------------------------------------------------

DX_FACTOR = {
    "MEDICAL_ACUTE": Decimal("1.00"),
    "MEDICAL_CHRONIC": Decimal("1.00"),
    "PSYCHIATRIC": Decimal("0.80"),
    "PREGNANCY_POSTPARTUM": Decimal("0.90"),
    "INJURY_REHAB": Decimal("1.00"),
}
MID_DURATION_DAYS = 30
MID_DURATION_BONUS_MINUTES = 30
LONG_DURATION_DAYS = 60
LONG_DURATION_BONUS_MINUTES = 60
SPED_FLOOR_FACTOR = Decimal("0.60")

VIRTUAL_CREDIT_FACTOR = Decimal("0.90")
CREDIT_ROUNDING_STEP = 5

SUPPORT_SHARE = Decimal("0.30")
ALLOC_ROUNDING_STEP = 5
ROLE_RANK = {"PRIMARY": 1, "SUPPORT": 2, "SPED_SERVICE": 3}

HAZARD_WEIGHTS = {
    "AGGRESSIVE_ANIMAL": 25,
    "NO_SECONDARY_EXIT": 15,
    "WEAPON_PRESENT_UNSECURED": 40,
    "SMOKE_OR_AIR_QUALITY": 10,
    "ACTIVE_INFECTION_RISK": 30,
    "UNLIT_ACCESS": 5,
    "NO_ADULT_PRESENT": 20,
}
SELF_REPORT_DISCOUNT = Decimal("0.75")
ESCORT_MITIGATION = 10
RISK_BLOCKED = 60
RISK_VIRTUAL_ONLY = 35
RISK_CLEARED_WITH_ESCORT = 15

FULL_CREDIT_RATIO = Decimal("0.90")
PARTIAL_CREDIT_RATIO = Decimal("0.75")
FORFEIT_RATIO = Decimal("0.50")

SAFETY_REVIEW_VALIDITY_DAYS = 60

IN_SERVICE_STATES = ("ACTIVE", "EXTENSION_PENDING", "TRANSITION_PLANNED")
MISSED_SESSION_STATES = ("STUDENT_UNAVAILABLE", "TEACHER_CANCELLED", "SAFETY_ABORTED")
OPEN_PLAN_STATES = ("DRAFT", "CLASSROOM_COORD_PENDING", "READY")


# --------------------------------------------------------------------------
# rounding helpers
# --------------------------------------------------------------------------

def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_half_up(value):
    """Round to a whole number, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to_step(value, step):
    """Divide by `step`, round half up to a whole number, multiply back."""
    return round_half_up(dec(value) / Decimal(step)) * step


def round_two_places(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def floor_weeks(days):
    """Completed weeks: a partial week contributes nothing."""
    if days <= 0:
        return 0
    return days // 7


def ceil_weeks(days):
    """Spanned weeks: a partial week counts in full."""
    if days <= 0:
        return 0
    return -(-days // 7)


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def student_of(case):
    return db.get("students", case["student_id"])


def rule_of(case):
    return db.get("entitlement_rules", case["entitlement_rule_id"])


def resolve_rule(grade_band, delivery_mode):
    """The single PUBLISHED rule for the pair; retired rules never participate."""
    for rule in db.rows("entitlement_rules"):
        if (
            rule["status"] == "PUBLISHED"
            and rule["grade_band"] == grade_band
            and rule["delivery_mode"] == delivery_mode
        ):
            return rule
    return None


def current_certification(case):
    for cert in db.by_case("certifications", case["id"]):
        if cert["is_current"] and cert["status"] == "ACCEPTED":
            return cert
    return None


def governing_review(case):
    """The finalized review that governs scheduling for this case."""
    for review in db.by_case("safety_reviews", case["id"]):
        if review["status"] == "FINALIZED":
            return review
    return None


def active_assignments(case):
    rows = [a for a in db.by_case("assignments", case["id"]) if a["status"] == "ACTIVE"]
    return sorted(rows, key=lambda a: (ROLE_RANK[a["role"]], a["created_at"], a["_seq"]))


def teacher_of(assignment):
    return db.get("teachers", assignment.get("teacher_id"))


# --------------------------------------------------------------------------
# calculations.weekly_entitlement_minutes (PRD §3.3)
# --------------------------------------------------------------------------

def weekly_entitlement_minutes(case, rule=None):
    student = student_of(case)
    rule = rule or rule_of(case)
    cert = current_certification(case)
    if rule is None or cert is None or case.get("diagnosis_category") is None:
        return case["weekly_entitled_minutes"]

    dx_factor = DX_FACTOR[case["diagnosis_category"]]
    effective_absence_days = cert["expected_absence_days"] + sum(
        e["requested_additional_days"]
        for e in db.by_case("extension_requests", case["id"])
        if e["status"] == "APPROVED"
    )
    if effective_absence_days >= LONG_DURATION_DAYS:
        duration_bonus = LONG_DURATION_BONUS_MINUTES
    elif effective_absence_days >= MID_DURATION_DAYS:
        duration_bonus = MID_DURATION_BONUS_MINUTES
    else:
        duration_bonus = 0

    adjusted = round_half_up(dec(rule["base_weekly_minutes"]) * dx_factor) + duration_bonus

    if student["special_ed_status"] == "IEP":
        sped_floor = round_half_up(dec(student["iep_service_minutes_weekly"]) * SPED_FLOOR_FACTOR)
    else:
        sped_floor = 0

    return min(max(adjusted, sped_floor), rule["cap_weekly_minutes"])


def recompute_weekly_entitlement(case, rule=None):
    db.set_field(case, "weekly_entitled_minutes", weekly_entitlement_minutes(case, rule))


# --------------------------------------------------------------------------
# calculations.assignment_minute_allocation + teacher_committed_minutes (§3.4)
# --------------------------------------------------------------------------

def per_support_minutes(weekly_entitled_minutes_value, support_count):
    if support_count <= 0:
        return 0
    return round_half_up_to_step(
        dec(weekly_entitled_minutes_value) * SUPPORT_SHARE / Decimal(support_count),
        ALLOC_ROUNDING_STEP,
    )


def recompute_allocation(case):
    """Distribute the case's weekly_entitled_minutes across its ACTIVE assignments."""
    active = active_assignments(case)
    primary = [a for a in active if a["role"] == "PRIMARY"]
    supports = [a for a in active if a["role"] == "SUPPORT"]
    speds = [a for a in active if a["role"] == "SPED_SERVICE"]

    if not primary:
        # No active primary: the allocation writes nothing and every row keeps 0.
        for assignment in active:
            db.set_field(assignment, "weekly_committed_minutes", 0)
    else:
        entitled = case["weekly_entitled_minutes"]
        per_support = per_support_minutes(entitled, len(supports))
        support_total = per_support * len(supports)
        for assignment in supports:
            db.set_field(assignment, "weekly_committed_minutes", per_support)
        for assignment in speds:
            db.set_field(assignment, "weekly_committed_minutes", 0)
        db.set_field(primary[0], "weekly_committed_minutes", entitled - support_total)

    recompute_teacher_commitments()


def prospective_allocation(case, role):
    """The allocation an assignment of `role` would receive were it ACTIVE now."""
    active = active_assignments(case)
    support_count = len([a for a in active if a["role"] == "SUPPORT"])
    has_primary = any(a["role"] == "PRIMARY" for a in active)
    if role == "SUPPORT":
        support_count += 1
    elif role == "PRIMARY":
        has_primary = True
    if not has_primary:
        return 0
    entitled = case["weekly_entitled_minutes"]
    per_support = per_support_minutes(entitled, support_count)
    if role == "SUPPORT":
        return per_support
    if role == "SPED_SERVICE":
        return 0
    return entitled - per_support * support_count


def select_teacher(case, role):
    """The selector policy of PRD §3.4: least-loaded eligible teacher wins."""
    student = student_of(case)
    mode = case["delivery_mode"]
    prospective = prospective_allocation(case, role)

    candidates = []
    for teacher in db.rows("teachers"):
        if mode == "VIRTUAL_SYNC":
            if teacher["safety_clearance_status"] not in ("CLEARED", "RESTRICTED"):
                continue
        elif teacher["safety_clearance_status"] != "CLEARED":
            continue
        if student["grade_band"] not in teacher["grade_bands"]:
            continue
        if mode in ("IN_HOME", "HYBRID") and not teacher["home_visit_eligible"]:
            continue
        if (
            teacher["committed_weekly_minutes"] + prospective
            > teacher["max_weekly_caseload_minutes"]
        ):
            continue
        candidates.append(teacher)

    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_TEACHER")
    candidates.sort(
        key=lambda t: (t["committed_weekly_minutes"], t["created_at"], t["_seq"])
    )
    return candidates[0]


def recompute_teacher_commitments():
    """Full re-sum of every teacher's committed minutes and over-cap flag."""
    assignments = list(db.store["assignments"].values())
    for teacher in db.store["teachers"].values():
        total = sum(
            a["weekly_committed_minutes"]
            for a in assignments
            if a.get("teacher_id") == teacher["id"] and a["status"] == "ACTIVE"
        )
        db.set_field(teacher, "committed_weekly_minutes", total)
        db.set_field(teacher, "over_cap", total > teacher["max_weekly_caseload_minutes"])


# --------------------------------------------------------------------------
# calculations.home_visit_risk_score (PRD §3.5)
# --------------------------------------------------------------------------

def risk_score(review):
    raw = sum(HAZARD_WEIGHTS[h] for h in set(review["hazard_findings"]))
    if review["scoring_variant"] == "SELF_REPORTED":
        score = round_half_up(dec(raw) * SELF_REPORT_DISCOUNT)
        return min(score, 100)
    score = raw - (ESCORT_MITIGATION if review["escort_available"] else 0)
    return min(max(score, 0), 100)


def band_clearance(score):
    if score >= RISK_BLOCKED:
        return "BLOCKED"
    if score >= RISK_VIRTUAL_ONLY:
        return "VIRTUAL_ONLY"
    if score >= RISK_CLEARED_WITH_ESCORT:
        return "CLEARED_WITH_ESCORT"
    return "CLEARED"


# --------------------------------------------------------------------------
# calculations.session_credited_minutes (PRD §3.6)
# --------------------------------------------------------------------------

def unrounded_credit(minutes, delivery_mode, rule):
    capped = min(minutes, rule["max_session_minutes"])
    if delivery_mode == "VIRTUAL_SYNC":
        return dec(capped) * VIRTUAL_CREDIT_FACTOR
    return dec(capped)


def credited_minutes(minutes, delivery_mode, rule):
    return round_half_up_to_step(
        unrounded_credit(minutes, delivery_mode, rule), CREDIT_ROUNDING_STEP
    )


# --------------------------------------------------------------------------
# ledger-driven case aggregates (PRD §3.6, §3.7)
# --------------------------------------------------------------------------

def case_ledger(case):
    return [e for e in db.rows("ledger_entries") if e["case_id"] == case["id"]]


def recompute_reported_apportionment(case):
    total = sum(e["apportionment_minutes"] for e in case_ledger(case))
    db.set_field(case, "reported_apportionment_minutes", total)


def recompute_makeup_obligation(case):
    sessions = db.by_case("sessions", case["id"])
    covered = set(
        s["makeup_for_session_id"]
        for s in sessions
        if s.get("makeup_for_session_id") and s["status"] == "DELIVERED"
    )
    total = sum(
        s["scheduled_minutes"]
        for s in sessions
        if s["status"] in MISSED_SESSION_STATES and s["id"] not in covered
    )
    db.set_field(case, "makeup_obligation_minutes", total)


def recompute_service_gap(case):
    """calculations.service_gap_minutes plus the ACCRUING <-> HELD threshold trigger."""
    if not case.get("service_start_date"):
        db.set_field(case, "service_gap_minutes", 0)
    else:
        completed_weeks = floor_weeks(
            (clock.get_date() - parse_date(case["service_start_date"])).days
        )
        expected_to_date = case["weekly_entitled_minutes"] * completed_weeks
        gap = max(0, expected_to_date - case["reported_apportionment_minutes"])
        db.set_field(case, "service_gap_minutes", gap)

    gap = case["service_gap_minutes"]
    entitled = case["weekly_entitled_minutes"]
    if gap >= entitled and case["funding_status"] in ("ACCRUING", "RECONCILED"):
        db.set_field(case, "funding_status", "HELD")
        enter_funding_hold(case)
    elif gap < entitled and case["funding_status"] == "HELD":
        db.set_field(case, "funding_status", "ACCRUING")
        db.touch(case)


def enter_funding_hold(case):
    """Conditional cascade into campus coordination when funding enters HELD."""
    for sync in db.by_case("pacing_syncs", case["id"]):
        if sync["ack_status"] == "ACKED":
            db.set_field(sync, "ack_status", "PENDING")
            db.set_field(sync, "acked_at", None)
        # DISPUTED rows are left exactly as they are.
    recompute_ack_counters(case)


# --------------------------------------------------------------------------
# calculations.transition_ack_counters (PRD §3.9)
# --------------------------------------------------------------------------

def recompute_ack_counters(case):
    syncs = db.by_case("pacing_syncs", case["id"])
    required = len(
        [s for s in syncs if s["ack_status"] in ("PENDING", "ACKED", "DISPUTED")]
    )
    acked = len([s for s in syncs if s["ack_status"] == "ACKED"])
    for plan in db.by_case("transition_plans", case["id"]):
        if plan["status"] not in OPEN_PLAN_STATES:
            continue
        db.set_field(plan, "required_ack_count", required)
        db.set_field(plan, "classroom_ack_count", acked)
        if (
            plan["status"] == "CLASSROOM_COORD_PENDING"
            and required >= 1
            and acked == required
            and case["funding_status"] != "HELD"
        ):
            db.set_field(plan, "status", "READY")
        elif plan["status"] == "READY" and (
            acked < required or case["funding_status"] == "HELD"
        ):
            db.set_field(plan, "status", "CLASSROOM_COORD_PENDING")


# --------------------------------------------------------------------------
# calculations.sped_compensatory_minutes (PRD §3.9)
# --------------------------------------------------------------------------

def recompute_compensatory_minutes(log, case):
    weeks_elapsed = 0
    if case.get("service_start_date"):
        weeks_elapsed = floor_weeks(
            (clock.get_date() - parse_date(case["service_start_date"])).days
        )
    owed = max(
        0,
        log["required_weekly_minutes"] * weeks_elapsed - log["delivered_cumulative_minutes"],
    )
    db.set_field(log, "compensatory_minutes_owed", owed)


# --------------------------------------------------------------------------
# calculations.case_apportionment_minutes (PRD §3.7)
# --------------------------------------------------------------------------

def window_weeks(case):
    if not case.get("service_start_date") or not case.get("certified_end_date"):
        return 0
    days = (
        parse_date(case["certified_end_date"]) - parse_date(case["service_start_date"])
    ).days + 1
    return ceil_weeks(days)


def elapsed_weeks(case):
    if not case.get("service_start_date"):
        return 0
    days = (clock.get_date() - parse_date(case["service_start_date"])).days + 1
    return ceil_weeks(days)


def service_weeks(case):
    return min(elapsed_weeks(case), window_weeks(case))


def _in_window(case, session):
    start = parse_date(case["service_start_date"])
    end = parse_date(case["certified_end_date"])
    service_date = parse_date(session["service_date"])
    return start <= service_date <= end


def provisional_apportionment(case):
    if not case.get("service_start_date") or not case.get("certified_end_date"):
        return 0
    rule = rule_of(case)
    if rule is None:
        return 0
    raw = 0
    for session in db.by_case("sessions", case["id"]):
        if session["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if not _in_window(case, session):
            continue
        if session["status"] == "DELIVERED":
            raw += session["credited_minutes"]
        else:
            raw += credited_minutes(
                session["scheduled_minutes"], session["delivery_mode"], rule
            )
    cap = case["weekly_entitled_minutes"] * window_weeks(case)
    return min(raw, cap)


def final_verified_apportionment(case):
    """Chronological walk with the weekly cap binding inside each ISO week."""
    if not case.get("service_start_date") or not case.get("certified_end_date"):
        return 0
    qualifying = [
        s
        for s in db.by_case("sessions", case["id"])
        if s["status"] == "DELIVERED" and s.get("verified_at") and _in_window(case, s)
    ]
    qualifying.sort(key=lambda s: (s["service_date"], s["created_at"], s["_seq"]))
    weekly_cap = case["weekly_entitled_minutes"]
    buckets = {}
    accepted = 0
    for session in qualifying:
        iso = parse_date(session["service_date"]).isocalendar()
        key = (iso[0], iso[1])
        room = max(0, weekly_cap - buckets.get(key, 0))
        take = min(session["credited_minutes"], room)
        buckets[key] = buckets.get(key, 0) + take
        accepted += take
    return accepted


def projected_unrounded_minutes(case):
    """Read-model diagnostic: the round-to-5 step is applied once, at the end."""
    rule = rule_of(case)
    if rule is None:
        return 0
    total = Decimal("0")
    for session in db.by_case("sessions", case["id"]):
        if session["status"] != "DELIVERED":
            continue
        total += unrounded_credit(
            session["actual_minutes"] or 0, session["delivery_mode"], rule
        )
    return round_half_up_to_step(total, CREDIT_ROUNDING_STEP)


# --------------------------------------------------------------------------
# calculations.funding_reconciliation_net (PRD §3.7)
# --------------------------------------------------------------------------

def reconcile_case(case):
    raw_final = final_verified_apportionment(case)
    weeks = service_weeks(case)
    entitled_total = case["weekly_entitled_minutes"] * weeks

    if entitled_total == 0:
        ratio = Decimal("0.00")
    else:
        ratio = round_two_places(dec(raw_final) / dec(entitled_total))

    db.set_field(case, "final_apportionment_minutes", raw_final)
    db.set_field(case, "delivery_ratio_pct", float(ratio))

    if ratio >= FULL_CREDIT_RATIO:
        recapture_rate = Decimal("0.00")
    elif ratio >= PARTIAL_CREDIT_RATIO:
        recapture_rate = Decimal("0.10")
    elif ratio >= FORFEIT_RATIO:
        recapture_rate = Decimal("0.25")
    else:
        recapture_rate = None  # forfeit band

    if recapture_rate is None:
        db.set_field(case, "recapture_minutes", raw_final)
        db.set_field(case, "net_apportionment_minutes", 0)
        db.set_field(case, "funding_status", "FORFEITED")
    else:
        shortfall = max(0, entitled_total - raw_final)
        recapture = round_half_up(dec(shortfall) * recapture_rate)
        db.set_field(case, "recapture_minutes", recapture)
        db.set_field(case, "net_apportionment_minutes", max(0, raw_final - recapture))
        db.set_field(case, "funding_status", "RECONCILED")


def funding_summary(case):
    return {
        "case_id": case["id"],
        "weekly_entitled_minutes": case["weekly_entitled_minutes"],
        "window_weeks": window_weeks(case),
        "service_weeks": service_weeks(case),
        "entitled_total_minutes": case["weekly_entitled_minutes"] * service_weeks(case),
        "provisional_minutes": provisional_apportionment(case),
        "final_verified_minutes": final_verified_apportionment(case),
        "projected_unrounded_minutes": projected_unrounded_minutes(case),
        "reported_apportionment_minutes": case["reported_apportionment_minutes"],
        "service_gap_minutes": case["service_gap_minutes"],
        "delivery_ratio_pct": case["delivery_ratio_pct"],
        "recapture_minutes": case["recapture_minutes"],
        "net_apportionment_minutes": case["net_apportionment_minutes"],
        "funding_status": case["funding_status"],
    }


# --------------------------------------------------------------------------
# ledger writes (PRD §3.6)
# --------------------------------------------------------------------------

def append_ledger_entry(
    case, session, attendance_code, apportionment_minutes, actor, reversal_of_entry_id=None
):
    return db.insert(
        "ledger_entries",
        {
            "case_id": case["id"],
            "session_id": session["id"],
            "reversal_of_entry_id": reversal_of_entry_id,
            "service_date": session["service_date"],
            "attendance_code": attendance_code,
            "apportionment_minutes": apportionment_minutes,
            "delivery_mode": session["delivery_mode"],
            "recorded_by_user_id": actor,
        },
        versioned=False,
    )


# --------------------------------------------------------------------------
# safety and compliance guards (PRD §3.5, §3.6 — tier 10)
# --------------------------------------------------------------------------

def check_scheduling_safety(case, teacher, session_mode, escort_confirmed, service_date):
    review = governing_review(case)
    if session_mode == "IN_HOME":
        if review is None:
            raise ApiError("ERR_SAFETY_REVIEW_MISSING")
        if parse_date(review["expires_on"]) < service_date:
            raise ApiError("ERR_SAFETY_REVIEW_EXPIRED")
    if review is not None and review["clearance"] == "BLOCKED":
        raise ApiError("ERR_SAFETY_CLEARANCE_BLOCKED")
    if session_mode == "IN_HOME":
        if case["delivery_mode"] == "VIRTUAL_SYNC" or (
            review is not None and review["clearance"] == "VIRTUAL_ONLY"
        ):
            raise ApiError("ERR_IN_HOME_NOT_PERMITTED")
    if teacher is not None:
        if teacher["safety_clearance_status"] == "EXPIRED":
            raise ApiError("ERR_TEACHER_CLEARANCE_EXPIRED")
        if session_mode == "IN_HOME" and not teacher["home_visit_eligible"]:
            raise ApiError("ERR_TEACHER_CLEARANCE_EXPIRED")
    if case["escort_required"] and session_mode == "IN_HOME" and escort_confirmed is not True:
        raise ApiError("ERR_ESCORT_REQUIRED_NOT_CONFIRMED")


def check_slot_conflict(assignment, start, end, session_mode, rule):
    """Tier 13: the teacher's busy intervals may not overlap (PRD §3.6)."""
    buffer_minutes = rule["travel_buffer_minutes"]

    def busy(session_start, session_end, mode):
        pad = timedelta(minutes=buffer_minutes if mode == "IN_HOME" else 0)
        return session_start - pad, session_end + pad

    a_start, a_end = busy(start, end, session_mode)
    for other in db.rows("sessions"):
        if other["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        other_assignment = db.get("assignments", other["assignment_id"])
        if other_assignment is None:
            continue
        if other_assignment.get("teacher_id") != assignment.get("teacher_id"):
            continue
        b_start, b_end = busy(
            parse_datetime(other["scheduled_start"]),
            parse_datetime(other["scheduled_end"]),
            other["delivery_mode"],
        )
        if a_start < b_end and b_start < a_end:
            raise ApiError("ERR_TEACHER_SLOT_CONFLICT")


def check_min_gap(case, start, end, service_date, rule):
    """Tier 13: same case, same service_date, closed-interval gap (PRD §3.6)."""
    for other in db.by_case("sessions", case["id"]):
        if other["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if other["service_date"] != service_date.isoformat():
            continue
        other_start = parse_datetime(other["scheduled_start"])
        other_end = parse_datetime(other["scheduled_end"])
        gap_minutes = (
            max((other_start - end).total_seconds(), (start - other_end).total_seconds())
            / 60.0
        )
        if gap_minutes < rule["min_gap_minutes"]:
            raise ApiError("ERR_SESSION_GAP_TOO_SHORT")


def check_daily_limit(case, minutes, service_date, rule):
    """Tier 14: the student's day is capped (PRD §3.6)."""
    total = minutes
    for other in db.by_case("sessions", case["id"]):
        if other["status"] not in ("SCHEDULED", "DELIVERED"):
            continue
        if other["service_date"] != service_date.isoformat():
            continue
        total += other["scheduled_minutes"]
    if total > rule["max_daily_minutes"]:
        raise ApiError("ERR_STUDENT_DAILY_LIMIT")


# --------------------------------------------------------------------------
# case closure cascade (PRD §3.9)
# --------------------------------------------------------------------------

def release_active_assignments(case):
    for assignment in db.by_case("assignments", case["id"]):
        if assignment["status"] != "ACTIVE":
            continue
        db.set_field(assignment, "status", "RELEASED")
        db.set_field(assignment, "release_reason", "CASE_CLOSED")
        db.set_field(assignment, "released_at", clock.instant_str())
        db.set_field(assignment, "weekly_committed_minutes", 0)
    recompute_teacher_commitments()


def cancel_scheduled_sessions(case):
    for session in db.by_case("sessions", case["id"]):
        if session["status"] == "SCHEDULED":
            db.set_field(session, "status", "CANCELLED_ADMIN")


def supersede_open_plans(case):
    for plan in db.by_case("transition_plans", case["id"]):
        if plan["status"] in OPEN_PLAN_STATES:
            db.set_field(plan, "status", "SUPERSEDED")


def deny_open_extension_requests(case):
    for request_row in db.by_case("extension_requests", case["id"]):
        if request_row["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
            db.set_field(request_row, "status", "DENIED")
            db.set_field(request_row, "decision_note", "case closed")
