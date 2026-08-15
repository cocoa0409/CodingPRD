"""Domain thresholds — numeric constants from PRD §3 calculations."""

# Aid-to-construction (PRD §3.2)
ATC = {
    "LINE_EXTENSION_CENTS_PER_FT": 1200,
    "ROAD_BORE_FLAT_CENTS": 150000,
    "TEMPORARY_MIN_CENTS": 50000,
    "FREE_ALLOWANCE_FT": 250,
    "OVERHEAD_THRESHOLD_CENTS": 200000,
    "OVERHEAD_PCT": 0.10,
}

# Billed demand (PRD §3.4)
DEMAND = {
    "IRRIGATION_MIN_BILLING_KW": 5.0,
    "RATCHET_PCT": 0.85,
}

# Capital-credit allocation (PRD §3.7)
ALLOCATION = {
    "IRRIGATION_WEIGHT_FACTOR": 0.5,
}

# Invoice write-off aging (PRD §3.4)
WRITE_OFF = {
    "MIN_AGE_DAYS": 180,
}

# Logical clock default (PRD §2.5)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Common test cooperative configuration
COOP_DEFAULTS = {
    "name": "Coop X",
    "fiscal_year_end_month": 12,
    "retirement_methods_allowed": ["FIFO_OLDEST", "PRO_RATA_PERCENTAGE"],
    "unclaimed_dormancy_years": 3,
    "annual_meeting_quorum_pct": 0.05,
    "irrigation_season_start_month": 4,
    "irrigation_season_end_month": 9,
}
