"""Domain thresholds and numeric constants from PRD §2.4, §3.4, §3.5, §3.6."""

# Logical clock (PRD §2.4): server default before any client call.
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_MONTH = "2026-08"

# Freight cost allocation (PRD §3.4).
FREIGHT = {
    "BASE_FEE_CENTS": 15000,
    "TIER1_LIMIT_MI": 100,
    "TIER1_RATE_CENTS_PER_MI": 450,
    "TIER2_LIMIT_MI": 300,
    "TIER2_RATE_CENTS_PER_MI": 320,
    "TIER3_RATE_CENTS_PER_MI": 210,
    "MAX_GENERATOR_FREIGHT_SHARE_CENTS": 60000,
}

# Acceptance quality gate (PRD §3.5): destination moisture may exceed the
# commitment's max_moisture_pct by at most this many percentage points.
MOISTURE_TOLERANCE_PCT = 2.0

# Sustainability credits (PRD §3.5, §3.8).
STANDARD_CREDIT_PER_TON = 1.0
ATTESTED_FACTOR = 0.92

# Credit tier thresholds (PRD §3.5): inclusive boundaries.
SILVER_THRESHOLD_CREDITS = 100
GOLD_THRESHOLD_CREDITS = 250

# Rejection tolerance (PRD §3.6): fraction of committed_monthly_tons.
REJECTION_TOLERANCE_PCT = 0.20

# Common test defaults.
TEST_DEFAULTS = {
    "DESTINATION_STATE": "PA",
    "INDEX_PRICE_CENTS_PER_TON": 300,
    "INDEX_EFFECTIVE_FROM": "2026-01-01",
    "TERM_START": "2026-01-01",
    "TERM_END": "2026-12-31",
    "ELIGIBILITY_VALID_FROM": "2026-01-01",
    "ELIGIBILITY_VALID_UNTIL": "2027-01-01",
    "PERMIT_ISSUED_ON": "2026-01-01",
    "PERMIT_EXPIRES_ON": "2026-12-31",
    "MAX_MOISTURE_PCT": 10.0,
    "MAX_ARSENIC_PPM": 5.0,
    "LOADING_MOISTURE_PCT": 8.0,
    "DESTINATION_MOISTURE_PCT": 8.0,
    "DESTINATION_ARSENIC_PPM": 3.0,
    "DISTANCE_MILES": 50,
    "PICKUP_DATE": "2026-08-05",
}
