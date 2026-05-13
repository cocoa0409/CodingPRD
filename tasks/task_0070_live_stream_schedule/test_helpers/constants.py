"""Live Stream Schedule — domain thresholds and pricing constants from PRD.

These values are the ones the test_suite references when asserting numeric
outcomes; they reflect what PRD §3 says, not implementation defaults.
"""

# ---------------------------------------------------------------------------
# Slot fee calculation
# ---------------------------------------------------------------------------

PEAK_WINDOW_START_UTC_HOUR = 19  # 19:00 UTC inclusive
PEAK_WINDOW_END_UTC_HOUR = 23    # 23:00 UTC exclusive
PEAK_MULTIPLIER = 0.50
DEPOSIT_FRACTION = 0.30

TIER_DISCOUNT_PCT = {
    "BRONZE": 0,
    "SILVER": 5,
    "GOLD": 10,
    "PLATINUM": 15,
}

PACKAGE_DISCOUNT_PCT = {
    "STANDARD": 0,
    "COMBO_HALF_DAY": 8,
    "COMBO_FULL_DAY": 12,
    "PEAK_BUNDLE": 5,
}

# ---------------------------------------------------------------------------
# Commission calculation
# ---------------------------------------------------------------------------

RATE_BP = {
    "BRONZE": 1200,
    "SILVER": 1500,
    "GOLD": 1800,
    "PLATINUM": 2200,
}

TIER_BONUS_SALES_THRESHOLD_CENTS = 5_000_000
TIER_BONUS_PCT = 0.005
TAX_RATE = 0.10
RETURN_WINDOW_DAYS = 7

# ---------------------------------------------------------------------------
# Performance tier thresholds
# ---------------------------------------------------------------------------

PLATINUM_GMV_CENTS = 50_000_000
GOLD_GMV_CENTS = 10_000_000
SILVER_GMV_CENTS = 1_000_000

# Per PRD §3.1 — violation_score >= 50 forces BRONZE, also separate per-tier ceilings
PLATINUM_MAX_VIOLATION_SCORE = 5
GOLD_MAX_VIOLATION_SCORE = 10
SILVER_MAX_VIOLATION_SCORE = 20
DEMOTION_VIOLATION_SCORE = 50

# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------

FULL_REFUND_LEAD_HOURS = 72
PARTIAL_REFUND_LEAD_HOURS = 24
PARTIAL_REFUND_FRACTION = 0.50

# ---------------------------------------------------------------------------
# Violation penalty
# ---------------------------------------------------------------------------

SEVERITY_BY_TYPE = {
    "FALSE_ADVERTISING": 2,
    "WRONG_PRODUCT": 1,
    "VIOLATING_CONTENT": 3,
    "DATA_FRAUD": 4,
}
EVIDENCE_THRESHOLD = 3
BLACKLIST_SCORE = 100
SUSPENSION_SCORE = 50
SUSPENSION_DEFAULT_DAYS = 30
FINE_PER_SEVERITY_CENTS = 50_000

# ---------------------------------------------------------------------------
# Application & broadcast constraints
# ---------------------------------------------------------------------------

MIN_DURATION_MINUTES = 30
MAX_DURATION_HOURS = 8
MAX_LIVE_ASSOCIATIONS = 20
APPEAL_WINDOW_DAYS = 7
VIOLATION_ENFORCEMENT_WINDOW_DAYS = 7

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
