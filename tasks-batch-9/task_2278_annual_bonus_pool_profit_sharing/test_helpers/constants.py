"""Domain thresholds, curve breakpoints and the standard plan calendar."""

from decimal import Decimal, ROUND_HALF_UP

# ─── The logical clock ────────────────────────────────────────────────────
# Before anything sets it, the logical clock reads exactly this instant.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── The standard plan calendar used across the suite ─────────────────────
PLAN_PERIOD_START = "2026-01-01"
PLAN_PERIOD_END = "2027-01-01"  # exclusive, exactly 365 days after the start
PLAN_LAST_DAY = "2026-12-31"  # last day inside the half-open window
PAYMENT_DATE = "2027-03-15"
PAYMENT_DATE_CLOCK = "2027-03-15T00:00:00Z"

# ─── Proration ────────────────────────────────────────────────────────────
THRESHOLDS = {
    # Minimum-service gate: exactly 90 credited days is eligible, 89 is not.
    "MIN_CREDITED_DAYS": 90,
    # The first 30 collected unpaid-leave dates are credited anyway.
    "UNPAID_LEAVE_CREDIT_CAP": 30,
    # Fixed plan-year basis used by per-segment proration.
    "PLAN_YEAR_DAYS": 365,
    # Funding curve breakpoints on blended achievement.
    "FUNDING_CURVE_FLOOR_PCT": 80.00,
    "FUNDING_CURVE_TARGET_PCT": 100.00,
    "FUNDING_CURVE_CAP_PCT": 120.00,
    "FUNDING_MULTIPLIER_AT_FLOOR": 0.5000,
    "FUNDING_MULTIPLIER_AT_TARGET": 1.0000,
    "FUNDING_MULTIPLIER_CAP": 1.5000,
    # Metric achievement curve.
    "METRIC_ACHIEVEMENT_AT_THRESHOLD": 50.00,
    "METRIC_ACHIEVEMENT_AT_TARGET": 100.00,
    "METRIC_ACHIEVEMENT_CAP": 150.00,
    # A unit may store a scorecard up to 200.00 but it enters funding capped.
    "SCORECARD_STORAGE_MAX_PCT": 200.00,
    "SCORECARD_FUNDING_CAP_PCT": 150.00,
    # Utilization floor: funded_cents * 9950 / 10000, fraction discarded.
    "MIN_UTILIZATION_NUMERATOR": 9950,
    "MIN_UTILIZATION_DENOMINATOR": 10000,
    # Top-tier concentration.
    "TOP_TIER_RATIO": 1.50,
    "TOP_TIER_HEADCOUNT_DIVISOR": 4,
    "TOP_TIER_MINIMUM_CAP": 1,
    # Discretionary adjustments.
    "ADJUSTMENT_DOCUMENTATION_THRESHOLD_CENTS": 100000,
    "PER_AWARD_CAP_FLOOR_CENTS": 50000,
    "PER_AWARD_CAP_PCT": 25,
    "DEFAULT_DISCRETIONARY_BUDGET_PCT": 10.00,
    "MAX_DISCRETIONARY_BUDGET_PCT": 25.00,
    # Dispute resolution ceiling: twice the award's final_award_cents.
    "DISPUTE_ADJUSTMENT_MULTIPLE": 2,
    # Pagination band.
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}

# ─── Employer burden bands, keyed on a cents figure ───────────────────────
BURDEN_BANDS = (
    (5_000_000, 7.65),
    (20_000_000, 9.25),
)
BURDEN_TOP_RATE_PCT = 10.50


def burden_rate_pct_for(cents: int) -> float:
    """Return the employer burden rate for a cents figure using the three-band table."""
    for ceiling, rate in BURDEN_BANDS:
        if cents < ceiling:
            return rate
    return BURDEN_TOP_RATE_PCT


def round_half_up(value, places: int = 0):
    """Round a numeric value half up to ``places`` decimals."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


# ─── Standard scenario literals ───────────────────────────────────────────
TEST_DEFAULTS = {
    "COMPANY_WEIGHT_PCT": 50.00,
    "BUSINESS_UNIT_WEIGHT_PCT": 30.00,
    "INDIVIDUAL_WEIGHT_PCT": 20.00,
    "L5_TARGET_BONUS_PCT": 20.00,
    "L5_BASE_SALARY_CENTS": 20000000,
    "GUIDELINE_MIN_RATIO": 0.25,
    "GUIDELINE_MAX_RATIO": 2.00,
    "METRIC_THRESHOLD_VALUE": 900,
    "METRIC_TARGET_VALUE": 1000,
    "METRIC_MAX_VALUE": 1200,
    "FULL_YEAR_HIRE_DATE": "2025-03-01",
}
