"""Pure calculation kernels (SCAFFOLD.yaml `calculations`, PRD 2.5 / 2.6 / 3.x).

Every money figure is integer cents; every intermediate uses decimal.Decimal
with ROUND_HALF_UP (a remainder of exactly half a cent rounds away from zero).
No float arithmetic appears anywhere in this module.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

ZERO = Decimal("0")
HUNDRED = Decimal("100")

# --- pinned constants -------------------------------------------------------
THRESHOLD_ACHIEVEMENT_PCT = Decimal("50.00")
TARGET_ACHIEVEMENT_PCT = Decimal("100.00")
MAX_ACHIEVEMENT_PCT = Decimal("150.00")
BU_ACHIEVEMENT_CAP_PCT = Decimal("150.00")
INDIVIDUAL_COMPONENT_PCT = Decimal("100.00")

CURVE_FLOOR_PCT = Decimal("80.00")
CURVE_TARGET_PCT = Decimal("100.00")
CURVE_CAP_PCT = Decimal("120.00")
CURVE_FLOOR_MULTIPLIER = Decimal("0.5000")
CURVE_CAP_MULTIPLIER = Decimal("1.5000")

PLAN_DAY_BASIS = Decimal("365")
MIN_SERVICE_DAYS = 90
LEAVE_CREDIT_CAP_DAYS = 30
GOOD_LEAVER_REASONS = ("REDUNDANCY", "RETIREMENT", "DEATH", "DISABILITY")
BAD_LEAVER_REASONS = ("VOLUNTARY_RESIGNATION", "TERMINATED_FOR_CAUSE")

UNDER_UTILIZATION_BP = Decimal("9950")
TOP_TIER_RATIO = Decimal("1.50")
TOP_TIER_MAX_PCT = 25

ADJ_FLOOR_CENTS = 50000
PER_AWARD_CAP_PCT = Decimal("25")
DOC_REQUIRED_ABOVE_CENTS = 100000

BURDEN_TIER_1_CENTS = 5000000
BURDEN_TIER_2_CENTS = 20000000
BURDEN_RATE_TIER_1_PCT = Decimal("7.65")
BURDEN_RATE_TIER_2_PCT = Decimal("9.25")
BURDEN_RATE_TIER_3_PCT = Decimal("10.50")

ALLOCATED_STATUSES = ("PROPOSED", "CALIBRATED", "LOCKED")


# ---------------------------------------------------------------------------
# rounding primitives
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def cents(value):
    """ROUND_HALF_UP to whole cents, returned as a Python int."""
    return int(round_half_up(value, 0))


def pct2(value):
    return round_half_up(value, 2)


def ratio4(value):
    return round_half_up(value, 4)


def floor_div(value, divisor):
    return int(dec(value) // dec(divisor))


# ---------------------------------------------------------------------------
# 1. metric_achievement
# ---------------------------------------------------------------------------
def metric_achievement(actual, threshold, target, maximum):
    a, t, g, m = dec(actual), dec(threshold), dec(target), dec(maximum)
    if a < t:
        achievement = Decimal("0.00")
    elif a < g:
        achievement = THRESHOLD_ACHIEVEMENT_PCT + (a - t) / (g - t) * Decimal("50")
    elif a < m:
        achievement = TARGET_ACHIEVEMENT_PCT + (a - g) / (m - g) * Decimal("50")
    else:
        achievement = MAX_ACHIEVEMENT_PCT
    return pct2(achievement)


# ---------------------------------------------------------------------------
# 2. company_achievement
# ---------------------------------------------------------------------------
def company_achievement(metrics):
    total = ZERO
    for metric in metrics:
        if metric["status"] != "ACTUAL_ENTERED":
            continue
        total += dec(metric["weight_pct"]) / HUNDRED * dec(metric["achievement_pct"])
    return pct2(total)


# ---------------------------------------------------------------------------
# 3. bu_weighted_achievement
# ---------------------------------------------------------------------------
def bu_weighted_achievement(pools, total_target_cents):
    selected = [p for p in pools
                if p["calibration_status"] == "SCORECARD_CERTIFIED"
                and p["eligible_target_cents"] > 0]
    if not selected or not total_target_cents:
        return Decimal("0.00")
    numerator = ZERO
    for pool in selected:
        capped = min(BU_ACHIEVEMENT_CAP_PCT, dec(pool["bu_metric_achievement_pct"]))
        numerator += dec(pool["eligible_target_cents"]) * capped
    return pct2(numerator / dec(total_target_cents))


# ---------------------------------------------------------------------------
# 4. blended_achievement
# ---------------------------------------------------------------------------
def blended_achievement(company_weight, bu_weight, individual_weight,
                        company_pct, bu_pct):
    total = (dec(company_weight) / HUNDRED * dec(company_pct)
             + dec(bu_weight) / HUNDRED * dec(bu_pct)
             + dec(individual_weight) / HUNDRED * INDIVIDUAL_COMPONENT_PCT)
    return pct2(total)


# ---------------------------------------------------------------------------
# 5. funding_curve_multiplier
# ---------------------------------------------------------------------------
def funding_curve_multiplier(blended_pct):
    b = dec(blended_pct)
    if b < CURVE_FLOOR_PCT:
        multiplier = Decimal("0.0000")
    elif b < CURVE_TARGET_PCT:
        multiplier = Decimal("0.50") + (b - Decimal("80")) / Decimal("20") * Decimal("0.50")
    elif b < CURVE_CAP_PCT:
        multiplier = Decimal("1.00") + (b - Decimal("100")) / Decimal("20") * Decimal("0.50")
    else:
        multiplier = CURVE_CAP_MULTIPLIER
    return ratio4(multiplier)


# ---------------------------------------------------------------------------
# 6. segment target (one segment of participant_prorated_target)
# ---------------------------------------------------------------------------
def segment_target_cents(credited_days, base_salary_cents, target_bonus_pct):
    return cents(dec(credited_days) * dec(base_salary_cents)
                 * dec(target_bonus_pct) / HUNDRED / PLAN_DAY_BASIS)


def leaver_class(termination_reason):
    if termination_reason in GOOD_LEAVER_REASONS:
        return "GOOD_LEAVER"
    return "BAD_LEAVER"


# ---------------------------------------------------------------------------
# 7. pool_funding_split helpers
# ---------------------------------------------------------------------------
def pool_funded_cents(eligible_target_cents, multiplier):
    return cents(dec(eligible_target_cents) * dec(multiplier))


def min_utilization_cents(funded_cents):
    return floor_div(dec(funded_cents) * UNDER_UTILIZATION_BP, Decimal("10000"))


def discretionary_budget_cents(funded_pool_cents, discretionary_budget_pct):
    return cents(dec(funded_pool_cents) * dec(discretionary_budget_pct) / HUNDRED)


# ---------------------------------------------------------------------------
# 8. pool_distribution_state helpers
# ---------------------------------------------------------------------------
def max_top_tier_count(eligible_headcount):
    if eligible_headcount <= 0:
        return 0
    return max(1, eligible_headcount * TOP_TIER_MAX_PCT // 100)


def utilization_pct(allocated_cents, funded_cents):
    if not funded_cents:
        return Decimal("0.00")
    scaled = round_half_up(dec(allocated_cents) * Decimal("10000") / dec(funded_cents), 0)
    return pct2(scaled / HUNDRED)


def distribution_status(eligible_headcount, allocated, funded, min_utilization):
    if eligible_headcount == 0:
        return "NO_ELIGIBLE_PARTICIPANTS"
    if allocated > funded:
        return "OVER_ALLOCATED"
    if allocated < min_utilization:
        return "UNDER_UTILIZED"
    return "WITHIN_GUIDELINES"


def governance_posture(over_allocated_count, under_utilized_count):
    if over_allocated_count >= 2:
        return "BREACHED"
    if over_allocated_count == 1 or under_utilized_count >= 1:
        return "FLAGGED"
    return "COMPLIANT"


def allocation_ratio(proposed_allocation_cents, prorated_target_cents):
    if not prorated_target_cents:
        return Decimal("0.0000")
    return ratio4(dec(proposed_allocation_cents) / dec(prorated_target_cents))


# ---------------------------------------------------------------------------
# 9. discretionary_cap
# ---------------------------------------------------------------------------
def per_award_cap_cents(prorated_target_cents):
    return max(ADJ_FLOOR_CENTS,
               cents(dec(prorated_target_cents) * PER_AWARD_CAP_PCT / HUNDRED))


# ---------------------------------------------------------------------------
# 10. provisional_pool_funding / period_accrual_with_burden
# ---------------------------------------------------------------------------
def provisional_pool_cents(target_basis_cents, multiplier):
    return cents(dec(target_basis_cents) * dec(multiplier))


def unprorated_participant_target_cents(base_salary_cents, target_bonus_pct):
    return cents(dec(base_salary_cents) * dec(target_bonus_pct) / HUNDRED)


def cumulative_accrual_target_cents(provisional_pool, elapsed_days):
    return cents(dec(provisional_pool) * dec(elapsed_days) / PLAN_DAY_BASIS)


def burden_rate_pct(basis_cents):
    if basis_cents < BURDEN_TIER_1_CENTS:
        return BURDEN_RATE_TIER_1_PCT
    if basis_cents < BURDEN_TIER_2_CENTS:
        return BURDEN_RATE_TIER_2_PCT
    return BURDEN_RATE_TIER_3_PCT


def burden_cents(amount_cents, rate_pct):
    return cents(dec(amount_cents) * dec(rate_pct) / HUNDRED)
