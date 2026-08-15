"""Domain thresholds — numeric constants named by the PRD (§3).

Money is integer cents end to end (PRD §2.5). Day counts are calendar days.
"""

# Rent-variance materiality threshold (PRD §3.3: "at least 500 cents").
RENT_VARIANCE_THRESHOLD_CENTS = 500

# Readiness posture thresholds (PRD §3.9: strict > comparisons).
POSTURE_AT_RISK_PCT = 0.03
POSTURE_BLOCKED_PCT = 0.05

# Insurance loss-ratio tiers (PRD §3.7: exact decimal; 0.80 exactly is HIGH).
RISK_TIER_LOW_MAX = 0.40
RISK_TIER_ELEVATED_MAX = 0.80

# Expense normalization outlier band (PRD §3.5: strict comparisons).
OUTLIER_HIGH_FACTOR = 1.20
OUTLIER_LOW_FACTOR = 0.80
TRAILING_WINDOW_MONTHS = 12

# Severance tiers and cap (PRD §3.11).
HOURS_PER_YEAR = 2080
WEEKS_PER_YEAR = 52
SEVERANCE_CAP_WEEKS = 8

# Deposit interest accrual (PRD §3.10).
DAYS_PER_YEAR = 365

# Default true-up window (PRD §3.1).
DEFAULT_TRUE_UP_WINDOW_DAYS = 90

# Logical clock startup value (PRD §2.7).
CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"

# Common test data defaults.
TEST_DEFAULTS = {
    "PROPERTY_NAME": "Test Property",
    "ADDRESS": "1 Main St",
    "PURCHASE_PRICE_CENTS": 200_000_000,
    "EARNEST_MONEY_CENTS": 5_000_000,
    "CLOSING_DATE": "2026-09-12T00:00:00Z",
    "DILIGENCE_DEADLINE": "2026-09-01T00:00:00Z",
    "ASSESSMENT_RATIO": 0.40,
    "MILLAGE_RATE": 25.0,
    "PRIOR_YEAR_TAX_CENTS": 1_800_000,
    "UNIT_NUMBER": "1A",
    "FLOOR_PLAN": "1BR",
    "SQFT": 700,
    "MARKET_RENT_CENTS": 160_000,
    "RESIDENT_NAME": "R One",
    "LEASE_START": "2025-09-01T00:00:00Z",
    "LEASE_END": "2027-08-31T00:00:00Z",
    "CONTRACT_RENT_CENTS": 150_000,
    "TERM_MONTHS": 12,
    "DEPOSIT_AMOUNT_CENTS": 150_000,
    # 150000 x 0.02 x 376/365 rounds half up to 3090 (DAILY_ACCRUAL, lease
    # starting 2025-09-01 to closing 2026-09-12 = 376 days).
    "DAILY_INTEREST_376D_CENTS": 3_090,
    "STATED_DEPOSIT_RECONCILED_CENTS": 153_090,
    "ANNUAL_INTEREST_RATE": 0.02,
    "INSPECTOR_REF": "insp-1",
    "WALK_START": "2026-08-10T09:00:00Z",
    "WALK_END": "2026-08-10T10:00:00Z",
    "ANNUAL_SALARY_CENTS": 5_200_000,
    "ACCRUED_PTO_HOURS": 40,
    # round_half_up(5200000/2080) = 2500; 40h x 2500 = 100000.
    "HOURLY_RATE_CENTS": 2_500,
    "RETAIN_PTO_LIABILITY_CENTS": 100_000,
}
