"""Domain thresholds and named constants drawn from the PRD's stated rules.

Every value below is quoted or arithmetically named in PRD §2.3, §2.4, §3.1,
§3.2, §3.5, §3.6, §3.8 or §3.9.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC_RENDERED = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
MIN_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Program design defaults and bounds (PRD §3.1)
# ---------------------------------------------------------------------------

DEFAULT_PROSPECTIVE_COMPLIANCE_MONTHS = 36
DEFAULT_INSTALLMENT_MAX_COUNT = 12
LOOKBACK_MONTHS_MIN = 1
LOOKBACK_MONTHS_MAX = 120
PROSPECTIVE_COMPLIANCE_MONTHS_MIN = 12
PROSPECTIVE_COMPLIANCE_MONTHS_MAX = 120
INSTALLMENT_MAX_COUNT_MIN = 1
INSTALLMENT_MAX_COUNT_MAX = 24
POST_PROGRAM_MULTIPLIER_MIN = 1.00
POST_PROGRAM_MULTIPLIER_MAX = 3.00

# ---------------------------------------------------------------------------
# Statutory liability accrual (PRD §3.5)
# ---------------------------------------------------------------------------

TIER_1_MAX_DAYS_LATE = 90
TIER_2_MAX_DAYS_LATE = 365
TIER_1_PENALTY_RATE = 0.05
TIER_2_PENALTY_RATE = 0.15
TIER_3_PENALTY_RATE = 0.25
NONFILER_SURCHARGE_RATE = 0.05
DAILY_INTEREST_RATE = 0.00025

# ---------------------------------------------------------------------------
# High-liability haircut (PRD §3.5)
# ---------------------------------------------------------------------------

HAIRCUT_TIER_2_MIN_CENTS = 25000000  # "at least 250,000 dollars"
HAIRCUT_TIER_2_PCT = 0.25
HAIRCUT_TIER_1_MIN_CENTS = 5000000  # "at least 50,000 dollars"
HAIRCUT_TIER_1_PCT = 0.10
HAIRCUT_NONE_PCT = 0.00

# ---------------------------------------------------------------------------
# Payment plans, schedules and the waterfall (PRD §3.6)
# ---------------------------------------------------------------------------

MIN_DOWN_PAYMENT_PCT = 0.10
INSTALLMENT_PERIOD_DAYS = 30
INSTALLMENT_HORIZON_DAYS = 365
MIN_INSTALLMENT_CENTS = 2500
SWEEP_GRACE_DAYS = 30

# ---------------------------------------------------------------------------
# Compliance behavior score (PRD §3.2)
# ---------------------------------------------------------------------------

SCORE_BASE = 100
SCORE_MIN = 0
SCORE_MAX = 100
PENALTY_OPEN_CASE = 20
PENALTY_REFERRED_CASE = 30
PENALTY_NONFILER_PERIOD = 5
PENALTY_NONPARTICIPANT = 25
PENALTY_ISSUED_ACTION = 8
CREDIT_FULFILLED_AGREEMENT = 15
CREDIT_PROGRAM_PARTICIPATION = 18
CREDIT_FORGIVEN_NONFILER_PERIOD = 5

# ---------------------------------------------------------------------------
# Post-program enforcement escalation (PRD §3.9)
# ---------------------------------------------------------------------------

TIER_RATE_T0 = 0.10
TIER_RATE_T1 = 0.20
TIER_RATE_T2 = 0.35
BEHAVIOR_SCORE_FLOOR = 60
BEHAVIOR_ADJUSTMENT_RATE = 0.05
NO_BEHAVIOR_ADJUSTMENT = 0.00
PENALTY_CAP_PCT = 0.50
PENALTY_FLOOR_CENTS = 10000
NO_ESCALATION_MULTIPLIER = 1.00

# ---------------------------------------------------------------------------
# Revenue realization bands (PRD §3.8)
# ---------------------------------------------------------------------------

ON_TRACK_MIN_PCT = 0.9000
WATCH_MIN_PCT = 0.7000
REALIZATION_DECIMAL_PLACES = 4

# ---------------------------------------------------------------------------
# Canonical scenario values reused across the suite.
#
# These are the coordinates of the worked example the suite exercises most:
# a $10,000.00 SALES_USE liability for Q1 2025 that missed a 2025-10-27 due
# date, disclosed under a program whose window closes 2026-12-01.
# ---------------------------------------------------------------------------

CANONICAL_CLOCK = "2026-09-15T00:00:00Z"
CANONICAL_CLOCK_RENDERED = "2026-09-15T00:00:00.000Z"

CANONICAL_WINDOW_OPEN_AT = "2026-09-01T00:00:00Z"
CANONICAL_WINDOW_CLOSE_AT = "2026-12-01T00:00:00Z"
CANONICAL_WINDOW_CLOSE_AT_RENDERED = "2026-12-01T00:00:00.000Z"
CANONICAL_WINDOW_CLOSE_DATE = "2026-12-01"
CANONICAL_LAST_INSTANT_INSIDE_WINDOW = "2026-11-30T23:59:59Z"

CANONICAL_LOOKBACK_MONTHS = 36
CANONICAL_BASE_PENALTY_WAIVER_PCT = 1.00
CANONICAL_BASE_INTEREST_WAIVER_PCT = 0.50
CANONICAL_POST_PROGRAM_MULTIPLIER = 2.00
CANONICAL_REVENUE_FORECAST_CENTS = 100000000

CANONICAL_TERM_ELIGIBLE_START = "2020-01-01"
CANONICAL_TERM_ELIGIBLE_END = "2026-07-01"
CANONICAL_TERM_MIN_LIABILITY_CENTS = 50000

CANONICAL_AGREEMENT_LOOKBACK_START = "2023-09-01"
CANONICAL_AGREEMENT_LOOKBACK_END = "2026-06-30"

CANONICAL_RETURN_PERIOD_START = "2025-01-01"
CANONICAL_RETURN_PERIOD_END = "2025-03-31"
CANONICAL_RETURN_ORIGINAL_DUE_DATE = "2025-10-27"
CANONICAL_RETURN_REPORTED_TAX_CENTS = 1000000

# Derived figures for the canonical return, per PRD §3.5.
CANONICAL_DAYS_LATE = 400
CANONICAL_PENALTY_RATE = 0.25
CANONICAL_GROSS_PENALTY_CENTS = 250000
CANONICAL_GROSS_INTEREST_CENTS = 100000
CANONICAL_GROSS_LIABILITY_CENTS = 1350000
CANONICAL_WAIVED_PENALTY_CENTS = 250000
CANONICAL_WAIVED_INTEREST_CENTS = 50000
CANONICAL_WAIVED_AMOUNT_CENTS = 300000
CANONICAL_PAYABLE_INTEREST_CENTS = 50000
CANONICAL_BALANCE_DUE_CENTS = 1050000
CANONICAL_TOTAL_DUE_CENTS = 1050000

# Derived figures for the canonical 11-installment plan, per PRD §3.6.
CANONICAL_DOWN_PAYMENT_CENTS = 105000
CANONICAL_INSTALLMENT_COUNT = 11
CANONICAL_SCHEDULED_TOTAL_CENTS = 945000
CANONICAL_INSTALLMENT_BASE_CENTS = 85909
CANONICAL_INSTALLMENT_LAST_CENTS = 85910
CANONICAL_WATERFALL_PAYMENT_CENTS = 200000
CANONICAL_WATERFALL_TAIL_CENTS = 28182
