"""Domain thresholds — numeric constants named in the PRD (§2.5, §2.7, §2.8, §3.3, §3.7)."""

THRESHOLDS = {
    # Reel status ladder / cut-waste policy (PRD §2.7)
    "MIN_REMNANT_MM": 1000,
    "LOW_THRESHOLD_MM": 20000,
    # Pressure-test multiple (PRD §2.8)
    "TEST_PRESSURE_MULTIPLIER": 2.0,
    # Labor rate tiers in cents per minute (PRD §3.3)
    "LABOR_RATE_STD_CPM": 150,
    "LABOR_RATE_MID_CPM": 200,
    "LABOR_RATE_HIGH_CPM": 260,
    "DIA_STD_MAX_IN": 0.5,
    "DIA_MID_MAX_IN": 1.0,
    "EMERGENCY_LABOR_MULT": 1.5,
    # Compliance scoring (PRD §3.7)
    "PROBATION_THRESHOLD": 70,
    "DUE_SOON_DAYS": 30,
}

TEST_DEFAULTS = {
    # Logical clock default (PRD §2.5)
    "DEFAULT_CLOCK_ISO": "2026-08-01T00:00:00Z",
    # Customer defaults (PRD §3.1)
    "INSPECTION_INTERVAL_DAYS": 365,
    # Order defaults (PRD §3.3)
    "CRIMP_TOLERANCE_MM": 0.2,
    "CRIMP_COUNT": 2,
}
