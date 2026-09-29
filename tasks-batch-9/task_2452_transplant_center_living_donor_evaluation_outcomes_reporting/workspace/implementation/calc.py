"""All calculation rules and their declared constants.

Every money figure is an integer number of cents; every score/percentage is
computed with decimal.Decimal and half-up rounding.  float is never used for
arithmetic that reaches a response body.
"""

from decimal import Decimal

from util import add_days, ceil_div, dec, round_half_up, whole_minutes

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

NON_DIRECTED_EXTRA_DAYS = 7
MIN_RE_DISCLOSURE_DAYS = 2

BMI_HARD_MAX = Decimal("35.0")
BMI_SOFT_MIN = Decimal("30.0")
EGFR_HARD_MIN = Decimal("80.0")
EGFR_SOFT_MAX = Decimal("90.0")
SYSTOLIC_HARD_MIN = 160
SYSTOLIC_SOFT_MIN = 140
HBA1C_HARD_MIN = Decimal("6.5")
HBA1C_SOFT_MIN = Decimal("5.7")
MIN_DONOR_AGE_YEARS = 18
SENIOR_DONOR_AGE_YEARS = 60
HARDSHIP_SOFT_MIN = 7
SUPPORT_SOFT_MAX = 3

DEFERRAL_SURCHARGE = Decimal("1.5")
NDD_SURCHARGE = Decimal("2.0")
RISK_INDEX_CEILING = Decimal("8.0")

CROSS_MATCH_HOLD_MINUTES = 45
MAX_CIT_MINUTES = 1080
CHAIN_CIT_BUDGET_MINUTES = 2400
OFFER_RESPONSE_WINDOW_HOURS = 6

URGENCY_WEIGHT = Decimal("2.0")
ACTIVE_DAY_WEIGHT = Decimal("0.007")
DIALYSIS_YEAR_WEIGHT = Decimal("1.005")
CPRA_TIER_98 = Decimal("10.0")
CPRA_TIER_80 = Decimal("4.0")
CPRA_TIER_20 = Decimal("1.0")
PEDIATRIC_BONUS = Decimal("3.0")
PEDIATRIC_AGE_YEARS = 18

REQUIRED_FIELDS = {"SIX_MONTH": 12, "ONE_YEAR": 14, "TWO_YEAR": 10}
DELINQUENCY_GRACE_DAYS = 30
FOLLOW_UP_DUE_OFFSET_DAYS = {"SIX_MONTH": 180, "ONE_YEAR": 365, "TWO_YEAR": 730}

MIN_COHORT_SIZE = 10
FLAG_THRESHOLD = Decimal("0.85")
WATCH_THRESHOLD = Decimal("0.95")

MEDICAL_CAP_CENTS = 1000000
TRAVEL_CAP_CENTS = 350000
DONOR_LIFETIME_CAP_CENTS = 1500000
INSURANCE_PER_CLAIM_CAP_CENTS = 600000
NLDAC_PER_DONOR_CAP_CENTS = 800000

CIT_BREACH_RESTRICT_COUNT = 2

ABO_COMPATIBILITY = {
    "O": {"O", "A", "B", "AB"},
    "A": {"A", "AB"},
    "B": {"B", "AB"},
    "AB": {"AB"},
}

# enum vocabularies
ORGAN_TYPES = ("KIDNEY", "LIVER")
STAFF_ROLES = (
    "TRANSPLANT_COORDINATOR",
    "LIVING_DONOR_ADVOCATE",
    "EVALUATION_REVIEWER",
    "QUALITY_OFFICER",
    "SURGEON",
)
ABO_TYPES = ("O", "A", "B", "AB")
LISTING_STATUSES = (
    "WORKUP",
    "APPROVED_NOT_LISTED",
    "DECLINED",
    "ACTIVE",
    "INACTIVE_HOLD",
    "TRANSPLANTED",
    "REMOVED",
)
EVENT_TO_STATUSES = (
    "APPROVED_NOT_LISTED",
    "DECLINED",
    "ACTIVE",
    "INACTIVE_HOLD",
    "TRANSPLANTED",
    "REMOVED",
)
ADVOCACY_STATUSES = ("UNASSIGNED", "ASSIGNED", "DISCLOSED", "ATTESTED", "OBJECTED")
CLINICAL_STATUSES = ("PENDING", "CLEARED", "EXCLUDED", "DEFERRED")
OVERALL_STATUSES = (
    "REFERRED",
    "EVAL_IN_PROGRESS",
    "APPROVED",
    "CONDITIONAL_APPROVED",
    "EXCLUDED",
    "ADVOCATE_BLOCKED",
    "CHAIN_COMMITTED",
    "DONATED",
)
EVAL_DOMAINS = ("MEDICAL", "PSYCHOSOCIAL")
EVAL_STATUSES = ("SUBMITTED", "CLEARED", "EXCLUDED", "DEFERRED")
DETERMINATION_OUTCOMES = ("CLEARED", "EXCLUDED", "DEFERRED")
ADVOCACY_OUTCOMES = ("ATTESTED", "OBJECTED")
CHAIN_TYPES = ("PAIRED_LOOP", "NDD_CHAIN")
CHAIN_STATUSES = (
    "DRAFT",
    "VALIDATED",
    "SUSPENDED",
    "COMMITTED",
    "EXECUTING",
    "COMPLETED",
    "BROKEN",
)
SEGMENT_STATUSES = (
    "PLANNED",
    "OFFER_SENT",
    "ACCEPTED",
    "DECLINED",
    "WITHDRAWN",
    "TRANSPLANTED",
)
OFFER_RESPONSES = ("ACCEPT", "DECLINE")
BOOKING_ROLES = ("DONOR_RECOVERY", "RECIPIENT_IMPLANT")
BOOKING_STATUSES = ("ACTIVE", "CANCELLED", "COMPLETED")
FOLLOW_UP_INTERVALS = ("SIX_MONTH", "ONE_YEAR", "TWO_YEAR")
FOLLOW_UP_STATUSES = ("DUE", "SUBMITTED_COMPLETE", "INCOMPLETE", "DELINQUENT", "WAIVED")
REVIEW_STATUSES = ("DRAFT", "FINALIZED")
FLAG_LEVELS = ("NONE", "WATCH", "FLAGGED")
PLAN_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED", "CLOSED")
PLAN_ACTIONS = ("ACCEPT", "REJECT", "CLOSE")
CLAIM_TYPES = ("MEDICAL", "TRAVEL", "LOST_WAGES")
COVERAGE_SOURCES = ("RECIPIENT_INSURANCE", "NLDAC_GRANT", "PROGRAM_FUND")
CLAIM_STATUSES = ("SUBMITTED", "ADJUDICATED", "DENIED", "REVERSED")
CLAIM_DECISIONS = ("APPROVE", "DENY")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")


# --------------------------------------------------------------------------- #
# cooling_off_window
# --------------------------------------------------------------------------- #


def cooling_off_ends_at(program, donor, disclosure_at):
    base_days = program["cooling_off_days"]
    if donor.get("intended_recipient_id") is None:
        base_days = base_days + NON_DIRECTED_EXTRA_DAYS
    if donor.get("disclosure_sequence", 0) >= 2:
        effective_days = max(MIN_RE_DISCLOSURE_DAYS, ceil_div(base_days, 2))
    else:
        effective_days = base_days
    return add_days(disclosure_at, effective_days)


# --------------------------------------------------------------------------- #
# donor_exclusion_screen
# --------------------------------------------------------------------------- #


def donor_exclusion_screen(domain, findings, donor_age_years):
    """Return (sorted exclusion codes, hard_exclusion_count, risk_points)."""
    codes = []
    points = 0
    if domain == "MEDICAL":
        bmi = dec(findings.get("bmi"))
        egfr = dec(findings.get("egfr_ml_min"))
        systolic = findings.get("systolic_bp")
        hba1c = dec(findings.get("hba1c"))

        if bmi is not None and bmi > BMI_HARD_MAX:
            codes.append("EX_BMI_TOO_HIGH")
        elif bmi is not None and BMI_SOFT_MIN < bmi <= BMI_HARD_MAX:
            points += 2

        if egfr is not None and egfr < EGFR_HARD_MIN:
            codes.append("EX_RENAL_FUNCTION_LOW")
        elif egfr is not None and EGFR_HARD_MIN <= egfr < EGFR_SOFT_MAX:
            points += 3

        if systolic is not None and systolic >= SYSTOLIC_HARD_MIN:
            codes.append("EX_HYPERTENSION")
        elif systolic is not None and SYSTOLIC_SOFT_MIN <= systolic < SYSTOLIC_HARD_MIN:
            points += 2

        if hba1c is not None and hba1c >= HBA1C_HARD_MIN:
            codes.append("EX_DIABETES_RANGE")
        elif hba1c is not None and HBA1C_SOFT_MIN <= hba1c < HBA1C_HARD_MIN:
            points += 2

        if donor_age_years < MIN_DONOR_AGE_YEARS:
            codes.append("EX_UNDERAGE")
        elif donor_age_years >= SENIOR_DONOR_AGE_YEARS:
            points += 1
    else:
        if findings.get("coercion_flag"):
            codes.append("EX_COERCION_SUSPECTED")
        if findings.get("unmanaged_substance_use"):
            codes.append("EX_SUBSTANCE_USE")
        if not findings.get("decisional_capacity_ok", True):
            codes.append("EX_CAPACITY_ABSENT")

        hardship = findings.get("financial_hardship_score")
        support = findings.get("social_support_score")
        if hardship is not None and hardship >= HARDSHIP_SOFT_MIN:
            points += 3
        if support is not None and support <= SUPPORT_SOFT_MAX:
            points += 2

    return sorted(codes), len(codes), points


# --------------------------------------------------------------------------- #
# donor_risk_index  (dual variant)
# --------------------------------------------------------------------------- #


def screening_risk_index(medical_points, psychosocial_points):
    return round_half_up(
        Decimal("0.6") * medical_points + Decimal("0.4") * psychosocial_points, 2
    )


def final_risk_index(medical_points, psychosocial_points, deferral_count, is_non_directed):
    ndd = 1 if is_non_directed else 0
    total = (
        Decimal("0.5") * medical_points
        + Decimal("0.5") * psychosocial_points
        + DEFERRAL_SURCHARGE * deferral_count
        + NDD_SURCHARGE * ndd
    )
    return round_half_up(total, 2)


# --------------------------------------------------------------------------- #
# cold_ischemia_time  (dual variant)
# --------------------------------------------------------------------------- #


def planned_cit_minutes(cross_clamp_at, reperfusion_at):
    return whole_minutes(cross_clamp_at, reperfusion_at) + CROSS_MATCH_HOLD_MINUTES


def actual_cit_minutes(cross_clamp_at, reperfusion_at):
    return whole_minutes(cross_clamp_at, reperfusion_at)


# --------------------------------------------------------------------------- #
# waitlist_active_days / waitlist_priority_score
# --------------------------------------------------------------------------- #


def waitlist_active_days(events, clock):
    """events must already be ordered effective_at ASC, created_at ASC."""
    intervals = []
    open_at = None
    for event in events:
        if open_at is not None and event["from_status"] == "ACTIVE":
            intervals.append((open_at, event["effective_at"]))
            open_at = None
        if event["to_status"] == "ACTIVE":
            open_at = event["effective_at"]
    if open_at is not None:
        intervals.append((open_at, clock))

    merged = []
    for start, end in sorted(intervals, key=lambda pair: (pair[0], pair[1])):
        if end <= start:
            # a zero (or negative) length window contributes nothing, but it may
            # still be adjacent to a neighbour -- treat it as a point interval.
            end = start
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))

    total_seconds = 0
    for start, end in merged:
        total_seconds += int((end - start).total_seconds())
    return total_seconds // 86400


def waitlist_priority_score(medical_urgency_points, active_days_total, dialysis_years, cpra, age_years):
    c_urgency = round_half_up(dec(medical_urgency_points) * URGENCY_WEIGHT, 2)
    c_waiting = round_half_up(dec(active_days_total) * ACTIVE_DAY_WEIGHT, 2)
    c_dialysis = round_half_up(dec(dialysis_years) * DIALYSIS_YEAR_WEIGHT, 2)
    cpra_value = dec(cpra)
    if cpra_value >= Decimal("0.98"):
        c_cpra = CPRA_TIER_98
    elif cpra_value >= Decimal("0.80"):
        c_cpra = CPRA_TIER_80
    elif cpra_value >= Decimal("0.20"):
        c_cpra = CPRA_TIER_20
    else:
        c_cpra = Decimal("0.0")
    c_pediatric = PEDIATRIC_BONUS if age_years < PEDIATRIC_AGE_YEARS else Decimal("0.0")
    # each component is already rounded; the sum is NOT re-rounded
    return c_urgency + c_waiting + c_dialysis + c_cpra + c_pediatric


# --------------------------------------------------------------------------- #
# follow_up_completeness
# --------------------------------------------------------------------------- #


def submitted_field_count(submitted_fields, required_fields_count):
    distinct = set()
    for entry in submitted_fields or []:
        if isinstance(entry, str) and entry != "":
            distinct.add(entry)
    return min(len(distinct), required_fields_count)


def completeness_pct(count, required_fields_count):
    return round_half_up(Decimal(100) * Decimal(count) / Decimal(required_fields_count), 2)


# --------------------------------------------------------------------------- #
# program_follow_up_compliance
# --------------------------------------------------------------------------- #


COUNTABLE_FOLLOW_UP_STATUSES = ("DUE", "SUBMITTED_COMPLETE", "INCOMPLETE", "DELINQUENT")


def compliance_pct(rows, clock):
    countable = [
        row
        for row in rows
        if row["status"] in COUNTABLE_FOLLOW_UP_STATUSES and row["due_on"] <= clock
    ]
    if not countable:
        return Decimal("100.00")
    numerator = len([row for row in countable if row["status"] == "SUBMITTED_COMPLETE"])
    return round_half_up(
        Decimal(100) * Decimal(numerator) / Decimal(len(countable)), 2
    )


# --------------------------------------------------------------------------- #
# outcome_oe_ratio
# --------------------------------------------------------------------------- #


def outcome_metrics(cohort_size, observed_survivor_count, rate):
    expected_count = round_half_up(dec(cohort_size) * dec(rate), 2)
    if cohort_size < MIN_COHORT_SIZE:
        return expected_count, None, "NONE", False
    oe_ratio = round_half_up(dec(observed_survivor_count) / expected_count, 4)
    if oe_ratio < FLAG_THRESHOLD:
        flag = "FLAGGED"
    elif oe_ratio < WATCH_THRESHOLD:
        flag = "WATCH"
    else:
        flag = "NONE"
    return expected_count, oe_ratio, flag, flag == "FLAGGED"


# --------------------------------------------------------------------------- #
# donor_cost_reimbursement  (dual variant)
# --------------------------------------------------------------------------- #


def estimated_reimbursement(claim_type, submitted_amount_cents, lost_wage_days, program):
    if claim_type == "MEDICAL":
        cap = MEDICAL_CAP_CENTS
    elif claim_type == "TRAVEL":
        cap = TRAVEL_CAP_CENTS
    else:
        daily_cap = lost_wage_days * program["lost_wage_daily_cap_cents"]
        weekly_cap = ceil_div(lost_wage_days, 7) * program["lost_wage_weekly_cap_cents"]
        cap = min(daily_cap, weekly_cap)
    return min(submitted_amount_cents, cap)


def adjudicate_claim(claim, prior_adjudicated, prior_grant, fund_remaining):
    """Return (insurance_part, grant_part, fund_part, adjudicated, unfunded)."""
    estimated = claim["estimated_reimbursement_cents"]
    need = min(estimated, DONOR_LIFETIME_CAP_CENTS - prior_adjudicated)

    insurance_headroom = (
        INSURANCE_PER_CLAIM_CAP_CENTS
        if claim["coverage_source"] == "RECIPIENT_INSURANCE"
        else 0
    )
    insurance_part = min(need, insurance_headroom)
    remainder = need - insurance_part

    grant_eligible = claim["claim_type"] in ("TRAVEL", "LOST_WAGES")
    grant_headroom = (NLDAC_PER_DONOR_CAP_CENTS - prior_grant) if grant_eligible else 0
    grant_part = min(remainder, max(0, grant_headroom))
    remainder = remainder - grant_part

    fund_part = min(remainder, fund_remaining)

    adjudicated = insurance_part + grant_part + fund_part
    unfunded = estimated - adjudicated
    return insurance_part, grant_part, fund_part, adjudicated, unfunded
