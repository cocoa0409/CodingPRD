"""Domain thresholds and clock constants from the PRD narratives."""

# Logical clock startup default (PRD logical-clock rule).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Opening forecast constants (PRD grand-opening date protection rules).
PUNCH_BUFFER_DAYS = 10
SLIP_FACTOR_NONE_BP = 0
SLIP_FACTOR_PADDED_BP = 500
SLIP_FACTOR_HEAVY_BP = 1500

# Site budget-posture ratio bands in basis points (final ratio).
SITE_POSTURE_WITHIN_MAX_BP = 500
SITE_POSTURE_WATCH_MAX_BP = 1500

# Change-order tier bands in basis points (exact rational comparison).
CO_TIER_STANDARD_MAX_BP = 200
CO_TIER_ELEVATED_MAX_BP = 500

# Protection-posture slip bands in whole days.
SLIP_WATCH_MAX_DAYS = 7
SLIP_AT_RISK_MAX_DAYS = 21

# Bid evaluation weights (BEST_VALUE).
PRICE_WEIGHT = 0.7
TECH_WEIGHT = 0.3

# Common scenario defaults shared by fixtures.
TEST_DEFAULTS = {
    "PROGRAM_NAME": "FY26 Rollout",
    "FISCAL_YEAR": 2026,
    "TOTAL_BUDGET_CENTS": 500_000_000,
    "CONTINGENCY_POOL_CENTS": 5_000_000,
    "MARKET_NAME": "DFW",
    "STATE_CODE": "TX",
    "MAX_CREWS": 2,
    "MUNICIPALITY_CODE": "TX-DAL",
    "STATUTORY_REVIEW_DAYS": 10,
    "OBSERVED_AVG_REVIEW_DAYS": 20,
    "PERMIT_VALIDITY_DAYS": 180,
    "FEE_BASE_CENTS": 50_000,
    "FEE_PER_SQFT_CENTS": 250,
    "SITE_ADDRESS": "100 Main St",
    "SQUARE_FOOTAGE": 4000,
    "PHASE_WAVE": 1,
    "BUDGET_ALLOCATION_CENTS": 10_000_000,
    "TARGET_OPEN_DATE": "2026-09-01",
    "BID_OPEN_AT": "2026-05-01T00:00:00Z",
    "BID_CLOSE_AT": "2026-05-10T00:00:00Z",
    "MAX_DURATION_DAYS": 120,
    "BID_AMOUNT_CENTS": 9_000_000,
    "BID_DURATION_DAYS": 90,
    "BID_TECH_SCORE": 80,
}
