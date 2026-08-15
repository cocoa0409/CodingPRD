"""Domain thresholds — numeric constants named by the PRD (§2.4, §3.3, §3.6, §3.8)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Item high-value boundary, inclusive (PRD §3.1).
    "HIGH_VALUE_CENTS": 1000000,
    # Cleaning fee components (PRD §3.3).
    "CLEANING_BASE_CENTS": 12000,
    "DEODORIZATION_ADDER_CENTS": 4000,
    # Claim settlement constants (PRD §3.6).
    "DEPRECIATION_PCT_PER_YEAR": 10,
    "MAX_DEPRECIATION_PCT": 70,
    "FLOOR_PCT": 30,
    "RCV_CAP_CENTS": 250000,
    # Carrier invoice admin-fee tiers, keyed on pre-fee subtotal (PRD §3.8).
    "FEE_TIER1_MAX_CENTS": 100000,
    "FEE_TIER2_MAX_CENTS": 500000,
    "FEE_TIER1_PCT": 5,
    "FEE_TIER2_PCT": 7,
    "FEE_TIER3_PCT": 9,
    # Specialty referral default markup (PRD §3.3).
    "DEFAULT_MARKUP_PCT": 15,
    # Storage daily proration (PRD §2.5, §3.7).
    "DAYS_PER_YEAR": 365,
    "MONTHS_PER_YEAR": 12,
}

TEST_DEFAULTS = {
    "CARRIER_NAME": "Acme Mutual",
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-09-01",
    "FINALIZE_CLOCK_ISO": "2026-09-01T00:00:00Z",
}
