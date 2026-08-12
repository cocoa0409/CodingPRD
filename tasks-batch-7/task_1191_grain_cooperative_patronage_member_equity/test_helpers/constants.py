"""Domain thresholds and rates — numeric constants from PRD §3."""

# Per-commodity per-unit retain rates in cents per bushel (PRD §3.2).
RETAIN_RATES_CENTS_PER_BU = {
    "CORN": 8,
    "SOYBEAN": 10,
    "WHEAT": 6,
    "SORGHUM": 7,
    "SUNFLOWER": 9,
}

THRESHOLDS = {
    # Volume tier lower bounds in bushels (PRD §3.3, inclusive boundary).
    "TIER_T2_MIN_BU": 1000,
    "TIER_T3_MIN_BU": 10000,
    # Estate claim filing window in days (PRD §3.7).
    "ESTATE_CLAIM_WINDOW_DAYS": 90,
    # Default dormancy period for unclaimed equity (PRD §3.8).
    "DEFAULT_DORMANCY_YEARS": 5,
    # Office appointment slot length (PRD §3.6).
    "APPOINTMENT_SLOT_SECONDS": 1800,
    # Appeal window after a rejection (PRD §3.6).
    "APPEAL_WINDOW_DAYS": 30,
}

TIER_RATE_MOD = {"T1": 1.00, "T2": 1.05, "T3": 1.10}
QUALIFIED_FRACTION = 0.70

TEST_DEFAULTS = {
    "YEAR_START": "2025-09-01T00:00:00Z",
    "YEAR_END": "2026-08-31T00:00:00Z",
    "CLOSE_CLOCK": "2026-09-01T00:00:00Z",
}
