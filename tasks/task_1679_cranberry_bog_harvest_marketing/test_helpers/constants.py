"""Domain thresholds and test defaults — numeric constants from the PRD.

Grading tiers (PRD §3.6), flood lead time (PRD §3.4/§3.5), default frost
threshold (PRD §3.2), and the canonical season window used across tests.
"""

THRESHOLDS = {
    # Grade tier ladder (PRD §3.6)
    "GRADE_A_MIN_SCORE": 8.0,
    "GRADE_B_MIN_SCORE": 7.0,
    "GRADE_C_MIN_SCORE": 6.0,
    "GRADE_A_MAX_FM": 2.0,
    "GRADE_B_MAX_FM": 4.0,
    "GRADE_C_MAX_FM": 6.0,
    "GRADE_REJECT_FM_CAP": 6.0,
    # Premium multipliers (PRD §3.6)
    "PREMIUM_A": 1.10,
    "PREMIUM_B": 1.00,
    "PREMIUM_C": 0.90,
    "PREMIUM_REJECT": 0,
    # WET harvest flood lead (PRD §3.4/§3.5)
    "FLOOD_LEAD_HOURS": 24,
    # Default frost damage threshold (PRD §3.2)
    "DEFAULT_FROST_DAMAGE_THRESHOLD_C": -2.0,
}

TEST_DEFAULTS = {
    "YEAR": 2026,
    "HARVEST_WINDOW_START": "2026-09-15",
    "HARVEST_WINDOW_END": "2026-11-15",
    "BASELINE_BARRELS_PER_ACRE": 200,
    "STATION_CAPACITY": 5000,
    "ADVANCE_RATE_MAIN": 0.50,
    "ADVANCE_RATE_OVER_QUOTA": 0.25,
    "RETAIN_PCT": 0.20,
    "SCHEDULED_DATE": "2026-10-10",
    # Logical clock default before any set call (PRD §2.7)
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
}
