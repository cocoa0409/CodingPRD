"""The nine pinned calculations (PRD 2.7, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9)."""
from decimal import Decimal
from fractions import Fraction

import constants as C
import db
import util

PROVISIONAL_STATUSES = ("PENDING_VERIFICATION", "VERIFIED")
FINAL_STATUSES = ("VERIFIED",)


# --------------------------------------------------------------------------
# 1. cycle_requirement_derivation (PRD 3.4)
# --------------------------------------------------------------------------
def requirement_derivation(attorney, period_start, period_end):
    group = attorney.get("compliance_group")
    deadline = util.add_days(period_end, C.DEADLINE_OFFSET_DAYS.get(group, 0))
    if attorney.get("status") == "EXEMPT":
        return {
            "prorated": False,
            "required_total_minutes": 0,
            "required_ethics_minutes": 0,
            "required_technology_minutes": 0,
            "required_bias_minutes": 0,
            "filing_deadline": util.iso(deadline),
        }
    admission = util.parse_date_only(attorney.get("admission_date"))
    prorated = admission is not None and period_start <= admission < period_end
    if not prorated:
        months = C.CYCLE_MONTHS
    else:
        anchor = util.first_of_next_month(admission)
        months = util.whole_months_between(anchor, period_end)
        months = max(0, min(C.CYCLE_MONTHS, months))
    hours = Fraction(C.TOTAL_REQUIRED_MINUTES * months, C.CYCLE_MONTHS * C.CREDIT_HOUR_MINUTES)
    whole_hours = -((-hours.numerator) // hours.denominator)
    required_total = whole_hours * C.CREDIT_HOUR_MINUTES
    if (not prorated) or months >= C.PRORATION_SPECIALTY_THRESHOLD_MONTHS:
        ethics = C.ETHICS_REQUIRED_MINUTES
        technology = C.TECHNOLOGY_REQUIRED_MINUTES
        bias = C.BIAS_REQUIRED_MINUTES
    else:
        ethics = C.PRORATED_ETHICS_REQUIRED_MINUTES
        technology = C.PRORATED_TECHNOLOGY_REQUIRED_MINUTES
        bias = C.PRORATED_BIAS_REQUIRED_MINUTES
    return {
        "prorated": prorated,
        "required_total_minutes": required_total,
        "required_ethics_minutes": ethics,
        "required_technology_minutes": technology,
        "required_bias_minutes": bias,
        "filing_deadline": util.iso(deadline),
    }


# --------------------------------------------------------------------------
# 2. credit_record_category_proration (PRD 3.5)
# --------------------------------------------------------------------------
def allocations_for_course(course_id):
    return [a for a in db.all_rows("credit_allocations") if a.get("course_id") == course_id]


def category_proration(course, attended_minutes):
    total_minutes = course.get("total_minutes") or 0
    attended = min(int(attended_minutes), int(total_minutes))
    alloc = {}
    for row in allocations_for_course(course["id"]):
        alloc[row["category"]] = alloc.get(row["category"], 0) + int(row["minutes"])
    credited = {}
    for category in C.PRORATION_ORDER:
        allocated = alloc.get(category, 0)
        if total_minutes <= 0 or allocated <= 0 or attended <= 0:
            credited[category] = 0
            continue
        raw = Fraction(allocated * attended, total_minutes)
        floored = (raw.numerator // raw.denominator)
        credited[category] = (int(floored) // C.ROUNDING_INCREMENT_MINUTES) * C.ROUNDING_INCREMENT_MINUTES
    total = sum(credited[c] for c in C.PRORATION_ORDER)
    return {
        "credited_ethics_minutes": credited["ETHICS"],
        "credited_technology_minutes": credited["TECHNOLOGY"],
        "credited_bias_minutes": credited["BIAS_ELIMINATION"],
        "credited_general_minutes": credited["GENERAL"],
        "credited_minutes": total,
    }


def effective_format(course, verification_method):
    fmt = course.get("delivery_format")
    if fmt == "LIVE_IN_PERSON":
        return "LIVE"
    if fmt == "LIVE_WEBCAST":
        if verification_method in ("ATTENDANCE_CODE", "ROSTER"):
            return "LIVE"
        return "ON_DEMAND"
    if fmt == "ON_DEMAND":
        return "ON_DEMAND"
    return "SELF_STUDY"


# --------------------------------------------------------------------------
# 3. cycle_credit_application (PRD 3.6) — two variants over one algorithm
# --------------------------------------------------------------------------
CATEGORY_FIELD = {
    "ETHICS": "credited_ethics_minutes",
    "TECHNOLOGY": "credited_technology_minutes",
    "BIAS_ELIMINATION": "credited_bias_minutes",
    "GENERAL": "credited_general_minutes",
}


def records_of_cycle(cycle_id):
    rows = [r for r in db.all_rows("credit_records") if r.get("cycle_id") == cycle_id]
    rows.sort(key=lambda r: (r.get("completion_date") or "", r.get("created_at") or "", r.get("_seq") or 0))
    return rows


def credit_application(cycle, variant, carryover_in_general_override=None):
    """Run the credit application. Persists nothing; returns the full result."""
    wanted = PROVISIONAL_STATUSES if variant == "PROVISIONAL" else FINAL_STATUSES
    all_records = records_of_cycle(cycle["id"])
    inputs = [r for r in all_records if r.get("status") in wanted]

    self_study_used = 0
    on_demand_used = 0
    nonlive_used = 0
    reciprocity_used = 0
    totals = {"ETHICS": 0, "TECHNOLOGY": 0, "BIAS_ELIMINATION": 0, "GENERAL": 0}
    countable_total = 0
    live_total = 0
    per_record = {}

    for record in inputs:
        credited = int(record.get("credited_minutes") or 0)
        fmt = record.get("effective_format")
        room = credited
        if fmt == "SELF_STUDY":
            room = min(
                credited,
                C.SELF_STUDY_CAP_MINUTES - self_study_used,
                C.NONLIVE_CAP_MINUTES - nonlive_used,
            )
        elif fmt == "ON_DEMAND":
            room = min(
                credited,
                C.ON_DEMAND_CAP_MINUTES - on_demand_used,
                C.NONLIVE_CAP_MINUTES - nonlive_used,
            )
        if record.get("source") == "RECIPROCITY":
            room = min(room, C.RECIPROCITY_CAP_MINUTES - reciprocity_used)
        countable = max(0, room)
        per_record[record["id"]] = countable

        shortfall = credited - countable
        for bucket in C.TRUNCATION_ORDER:
            bucket_minutes = int(record.get(CATEGORY_FIELD[bucket]) or 0)
            taken = min(shortfall, bucket_minutes)
            totals[bucket] += bucket_minutes - taken
            shortfall -= taken

        countable_total += countable
        if fmt == "SELF_STUDY":
            self_study_used += countable
            nonlive_used += countable
        elif fmt == "ON_DEMAND":
            on_demand_used += countable
            nonlive_used += countable
        elif fmt == "LIVE":
            live_total += countable
        if record.get("source") == "RECIPROCITY":
            reciprocity_used += countable

    carry_general = cycle.get("carryover_in_general_minutes") or 0
    if carryover_in_general_override is not None:
        carry_general = carryover_in_general_override
    carry_ethics = cycle.get("carryover_in_ethics_minutes") or 0

    effective_total = countable_total + carry_general + carry_ethics
    effective_ethics = totals["ETHICS"] + carry_ethics
    deficiency_total = max(0, int(cycle.get("required_total_minutes") or 0) - effective_total)
    deficiency_ethics = max(0, int(cycle.get("required_ethics_minutes") or 0) - effective_ethics)
    deficiency_technology = max(0, int(cycle.get("required_technology_minutes") or 0) - totals["TECHNOLOGY"])
    deficiency_bias = max(0, int(cycle.get("required_bias_minutes") or 0) - totals["BIAS_ELIMINATION"])

    return {
        "variant": variant,
        "per_record": per_record,
        "all_records": all_records,
        "records_counted": len(inputs),
        "records_excluded": len([r for r in all_records if r.get("status") in ("REJECTED", "VOIDED")]),
        "earned_countable_minutes": countable_total,
        "earned_ethics_minutes": totals["ETHICS"],
        "earned_technology_minutes": totals["TECHNOLOGY"],
        "earned_bias_minutes": totals["BIAS_ELIMINATION"],
        "earned_general_minutes": totals["GENERAL"],
        "earned_live_minutes": live_total,
        "self_study_used_minutes": self_study_used,
        "on_demand_used_minutes": on_demand_used,
        "nonlive_used_minutes": nonlive_used,
        "reciprocity_used_minutes": reciprocity_used,
        "deficiency_total_minutes": deficiency_total,
        "deficiency_ethics_minutes": deficiency_ethics,
        "deficiency_technology_minutes": deficiency_technology,
        "deficiency_bias_minutes": deficiency_bias,
        "carryover_in_general_effective": carry_general,
    }


def has_any_deficiency(res):
    return (
        res["deficiency_total_minutes"] > 0
        or res["deficiency_ethics_minutes"] > 0
        or res["deficiency_technology_minutes"] > 0
        or res["deficiency_bias_minutes"] > 0
    )


# --------------------------------------------------------------------------
# 4. carryover_determination (PRD 3.8)
# --------------------------------------------------------------------------
def carryover_determination(cycle, res):
    if cycle.get("carryover_election") == "WAIVE_CARRYOVER" or has_any_deficiency(res):
        return 0, 0
    surplus = (
        res["earned_countable_minutes"]
        + (cycle.get("carryover_in_general_minutes") or 0)
        + (cycle.get("carryover_in_ethics_minutes") or 0)
        - int(cycle.get("required_total_minutes") or 0)
    )
    out_general = min(
        C.CARRYOVER_CAP_GENERAL_MINUTES,
        max(0, surplus),
        res["earned_live_minutes"],
    )
    ethics_surplus = res["earned_ethics_minutes"] - int(cycle.get("required_ethics_minutes") or 0)
    out_ethics = min(C.CARRYOVER_CAP_ETHICS_MINUTES, max(0, ethics_surplus))
    return out_general, out_ethics


# --------------------------------------------------------------------------
# 5. late_fee_assessment (PRD 3.9) — seven pinned steps
# --------------------------------------------------------------------------
def late_fee_cents(cycle):
    # Step 1: suppress unreliable carryover.
    effective_carry = cycle.get("carryover_in_general_minutes") or 0
    previous = db.get("compliance_cycles", cycle.get("previous_cycle_id"))
    if previous is not None and previous.get("credit_status") == "OPEN":
        effective_carry = 0
    # Step 2: final variant with that substitution.
    res = credit_application(cycle, "FINAL", carryover_in_general_override=effective_carry)
    return late_fee_from_result(res)


def late_fee_from_result(res):
    # Step 3: total the shortfall across all four requirements.
    deficiency_minutes = (
        res["deficiency_total_minutes"]
        + res["deficiency_ethics_minutes"]
        + res["deficiency_technology_minutes"]
        + res["deficiency_bias_minutes"]
    )
    # Step 4: convert to whole hours, rounding up.
    hours = util.ceil_div(deficiency_minutes, C.CREDIT_HOUR_MINUTES)
    # Step 5: base tier from the rounded hour count.
    if hours == 0:
        base = C.LATE_FEE_BASE_TIERS_CENTS["0"]
    elif hours <= 5:
        base = C.LATE_FEE_BASE_TIERS_CENTS["1_5"]
    elif hours <= 15:
        base = C.LATE_FEE_BASE_TIERS_CENTS["6_15"]
    else:
        base = C.LATE_FEE_BASE_TIERS_CENTS["16_plus"]
    # Step 6: surcharge on the hour count capped at twenty.
    surcharge = C.LATE_FEE_PER_HOUR_CENTS * min(hours, C.LATE_FEE_SURCHARGE_HOUR_CAP)
    # Step 7: cap the sum.
    return min(C.LATE_FEE_CAP_CENTS, base + surcharge)


# --------------------------------------------------------------------------
# 6. provider_risk_score (PRD 3.9) — two weightings
# --------------------------------------------------------------------------
def _clamp_rate(value):
    if value < 0:
        return Fraction(0)
    if value > 1:
        return Fraction(1)
    return value


def risk_score_variant_for(provider):
    if provider.get("accreditation_status") == "ACCREDITED":
        return "SELF_CERTIFIED_WEIGHTING"
    return "REVIEWED_WEIGHTING"


def compute_risk_score(provider):
    """Returns (Decimal score rounded to 2dp, variant)."""
    variant = risk_score_variant_for(provider)

    late = int(provider.get("attendance_reports_late_count") or 0)
    total = int(provider.get("attendance_reports_total_count") or 0)
    delinquency = Fraction(late, total if total > 0 else 1)

    complaints = int(provider.get("substantiated_complaint_count") or 0)
    complaint = Fraction(complaints, C.COMPLAINT_NORMALIZER)

    findings = int(provider.get("audit_findings_count") or 0)
    if variant == "SELF_CERTIFIED_WEIGHTING":
        denominator = int(provider.get("courses_self_certified_count") or 0)
    else:
        denominator = int(provider.get("courses_total_count") or 0)
    finding = Fraction(findings, denominator if denominator > 0 else 1)

    anchor = provider.get("last_audit_closed_at") or provider.get("accreditation_term_start")
    if anchor is None:
        staleness = Fraction(1)
    else:
        months = util.whole_months_between(util.parse_dt(anchor), util.now_dt())
        staleness = Fraction(max(0, months), C.STALENESS_NORMALIZER_MONTHS)

    delinquency = _clamp_rate(delinquency)
    complaint = _clamp_rate(complaint)
    finding = _clamp_rate(finding)
    staleness = _clamp_rate(staleness)

    weighted = (
        Fraction(Decimal(C.RISK_WEIGHT_DELINQUENCY)) * delinquency
        + Fraction(Decimal(C.RISK_WEIGHT_COMPLAINT)) * complaint
        + Fraction(Decimal(C.RISK_WEIGHT_FINDING)) * finding
        + Fraction(Decimal(C.RISK_WEIGHT_STALENESS)) * staleness
    )
    exact = Decimal(weighted.numerator) / Decimal(weighted.denominator)
    return util.round_half_up(exact, 2), variant


# --------------------------------------------------------------------------
# 7. audit_sample_selection (PRD 3.9)
# --------------------------------------------------------------------------
SAMPLEABLE_COURSE_STATUSES = ("APPROVED", "EXPIRED", "SUSPENDED_PENDING_REVIEW")


def audit_sample_pool(audit):
    start = util.parse_dt(audit.get("audit_period_start"))
    end = util.parse_dt(audit.get("audit_period_end"))
    pool = []
    for course in db.all_rows("courses"):
        if course.get("provider_id") != audit.get("provider_id"):
            continue
        if course.get("status") not in SAMPLEABLE_COURSE_STATUSES:
            continue
        presented = util.parse_dt(course.get("presented_at"))
        if presented is None or presented < start or presented > end:
            continue
        pool.append(course)
    pool.sort(key=lambda c: (c.get("presented_at") or "", c.get("created_at") or "", c.get("_seq") or 0))
    return pool


def sample_target(risk_score_at_open):
    score = Decimal(str(risk_score_at_open if risk_score_at_open is not None else "0"))
    if score >= Decimal(C.RISK_SAMPLE_TIER_HIGH):
        return C.RISK_SAMPLE_N_HIGH
    if score >= Decimal(C.RISK_SAMPLE_TIER_MID):
        return C.RISK_SAMPLE_N_MID
    return C.RISK_SAMPLE_N_LOW


# --------------------------------------------------------------------------
# 8. reciprocity_credit_conversion (PRD 3.7)
# --------------------------------------------------------------------------
def convert_reciprocity(claim):
    jurisdiction = claim.get("origin_jurisdiction")
    hour_minutes = C.ORIGIN_HOUR_MINUTES[jurisdiction]
    hours = Fraction(str(claim.get("origin_credit_hours")))
    origin_minutes = hours * hour_minutes
    floored = origin_minutes.numerator // origin_minutes.denominator
    converted = (int(floored) // C.ROUNDING_INCREMENT_MINUTES) * C.ROUNDING_INCREMENT_MINUTES
    category = C.ORIGIN_CATEGORY_MAP[claim.get("origin_category")]
    return converted, category


# --------------------------------------------------------------------------
# 9. attendance_report_lateness (PRD 3.5)
# --------------------------------------------------------------------------
def roster_lateness(session_date):
    due_at = util.add_days(session_date, C.ROSTER_DUE_DAYS)
    hard_close = util.add_days(session_date, C.ROSTER_HARD_WINDOW_DAYS)
    now = util.now_dt()
    if now > hard_close:
        return None
    if now <= due_at:
        return {"due_at": due_at, "hard_close": hard_close, "days_late": 0, "status": "ACCEPTED"}
    return {
        "due_at": due_at,
        "hard_close": hard_close,
        "days_late": util.days_between_ceil(now, due_at),
        "status": "ACCEPTED_LATE",
    }
