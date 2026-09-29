"""Domain thresholds, rates and reference instants stated by the PRD."""

from __future__ import annotations

from .types import (
    DEFICIENCY_ATTESTATION_LATE,
    DEFICIENCY_GAG_CLAUSE,
    DEFICIENCY_MRF_REFRESH,
    DEFICIENCY_RXDC_LATE,
    DEFICIENCY_TOOL_SLA,
    DeficiencyType,
)

# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------

#: "At startup the clock reads 2026-08-01T00:00:00Z."
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Accrual pricing
# ---------------------------------------------------------------------------

#: Daily rate in cents per deficiency family.
DAILY_RATE_CENTS: dict[DeficiencyType, int] = {
    DEFICIENCY_MRF_REFRESH: 10_000,
    DEFICIENCY_TOOL_SLA: 5_000,
    DEFICIENCY_RXDC_LATE: 20_000,
    DEFICIENCY_GAG_CLAUSE: 15_000,
    DEFICIENCY_ATTESTATION_LATE: 12_000,
}

RATE_MRF_REFRESH_CENTS = DAILY_RATE_CENTS[DEFICIENCY_MRF_REFRESH]
RATE_TOOL_SLA_CENTS = DAILY_RATE_CENTS[DEFICIENCY_TOOL_SLA]
RATE_RXDC_LATE_CENTS = DAILY_RATE_CENTS[DEFICIENCY_RXDC_LATE]
RATE_GAG_CLAUSE_CENTS = DAILY_RATE_CENTS[DEFICIENCY_GAG_CLAUSE]
RATE_ATTESTATION_LATE_CENTS = DAILY_RATE_CENTS[DEFICIENCY_ATTESTATION_LATE]

#: Size multiplier tiers keyed on covered_lives.
SIZE_MULTIPLIER_SMALL = 1.0  # fewer than 500 covered lives
SIZE_MULTIPLIER_MEDIUM = 1.5  # at least 500 and at most 4,999
SIZE_MULTIPLIER_LARGE = 2.0  # 5,000 or more

SIZE_TIER_MEDIUM_FLOOR = 500
SIZE_TIER_LARGE_FLOOR = 5_000

#: "clamped so that it never exceeds 100,000,000 cents"
PENALTY_CAP_CENTS = 100_000_000

#: Non-accrual entries carry these fixed pricing fields.
NON_ACCRUAL_DAILY_RATE_CENTS = 0
NON_ACCRUAL_DAYS_OPEN = 0
NON_ACCRUAL_SIZE_MULTIPLIER = 1.0

# ---------------------------------------------------------------------------
# Deficiency points and posture ladder
# ---------------------------------------------------------------------------

POINTS_MISSED_CYCLE = 3
POINTS_LATE_CERTIFIED_CYCLE = 2
POINTS_NON_COMPLIANT_CONTRACT = 6
POINTS_TOOL_SLA_BREACH = 2
POINTS_RXDC_LATE_SUBMISSION = 5
POINTS_ATTESTATION_DEFICIENCY = 5
POINTS_UNREASONABLE_DISCLOSURE = 3

#: "Exactly 6 points is DEFICIENT; exactly 12 is FROZEN."
DEFICIENT_THRESHOLD_POINTS = 6
FROZEN_THRESHOLD_POINTS = 12
AT_RISK_THRESHOLD_POINTS = 1

# ---------------------------------------------------------------------------
# Refresh cycles
# ---------------------------------------------------------------------------

#: "a five-day grace window on top of the period itself"
REFRESH_GRACE_DAYS = 5

#: The derived deadline's time-of-day component.
DEADLINE_TIME_SUFFIX = "T23:59:59.999Z"

# ---------------------------------------------------------------------------
# Price comparison tool
# ---------------------------------------------------------------------------

#: "at least 500 covered items and services"
REQUIRED_COVERED_ITEMS = 500

#: "defaulting to 99.00 when omitted"
DEFAULT_SLA_TARGET_UPTIME_PCT = 99.00

MINUTES_PER_DAY = 1440
MINUTES_IN_30_DAY_MONTH = 30 * MINUTES_PER_DAY  # 43,200
MINUTES_IN_31_DAY_MONTH = 31 * MINUTES_PER_DAY  # 44,640

#: On a thirty-day month with a 99.00 target these are the two sides of the edge.
DOWNTIME_MINUTES_EXACTLY_ON_TARGET = 432
DOWNTIME_MINUTES_ONE_STEP_BELOW_TARGET = 435
UPTIME_PCT_EXACTLY_ON_TARGET = 99.00
UPTIME_PCT_ONE_STEP_BELOW_TARGET = 98.99

# ---------------------------------------------------------------------------
# Amendments and gag review
# ---------------------------------------------------------------------------

#: "Revision is refused once `round` has reached 3"
MAX_NEGOTIATION_ROUNDS = 3

#: "`remediation_round` must be strictly below 2"
MAX_REMEDIATION_ROUNDS = 2

# ---------------------------------------------------------------------------
# Compensation reasonableness
# ---------------------------------------------------------------------------

WEIGHT_PRICE = 40
WEIGHT_SCOPE = 25
WEIGHT_DISCLOSURE = 35

#: "or by 3.0 if the ratio exceeds 3.0"
PRICE_RATIO_CAP = 3.0

#: "The threshold is 55.00 and the comparison is inclusive."
UNREASONABLE_THRESHOLD = 55.00

MIN_SCORE_INPUT = 1
MAX_SCORE_INPUT = 5
MIN_BENCHMARK_MEDIAN_CENTS = 1

#: Two decimal places, round half up — comparisons use this tolerance.
SCORE_TOLERANCE = 0.01

# ---------------------------------------------------------------------------
# Prescription-drug reconciliation
# ---------------------------------------------------------------------------

REBATE_CAP_PCT_LOW_TIER = 0.25  # gross spend below 10,000,000 cents
REBATE_CAP_PCT_MID_TIER = 0.20  # at least 10,000,000 and below 100,000,000
REBATE_CAP_PCT_HIGH_TIER = 0.15  # 100,000,000 cents or more

REBATE_TIER_MID_FLOOR_CENTS = 10_000_000
REBATE_TIER_HIGH_FLOOR_CENTS = 100_000_000

MIN_REFERENCE_YEAR = 2020

# ---------------------------------------------------------------------------
# Remediation
# ---------------------------------------------------------------------------

#: "`abatement_posted_cents` is 0.50 multiplied by that base"
ABATEMENT_FRACTION = 0.50
