"""Domain thresholds and defaults used across tests (PRD §2.5, §3.4, §3.5)."""

# Logical clock default and the canonical test instant (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"
CLOCK_JUNE_15 = "2026-06-15T00:00:00Z"
CLOCK_JUNE_20 = "2026-06-20T00:00:00Z"

# Variable-consideration constraint caps by risk tier (PRD §3.5).
VC_CAPS = {"STANDARD": 0.85, "ELEVATED": 0.70, "HIGH": 0.50}

# Scenario probability weights must sum to exactly this (PRD §3.5).
SCENARIO_WEIGHT_TOTAL_BPS = 10000

# Combination assessment window in whole days (PRD §3.4).
COMBINATION_WINDOW_DAYS = 30

# Common dates.
SIGNED_DATE = "2026-05-20"
JUNE_PERIOD = {"period_code": "2026-06", "start_date": "2026-06-01", "end_date": "2026-07-01"}
MAY_PERIOD = {"period_code": "2026-05", "start_date": "2026-05-01", "end_date": "2026-06-01"}
SSP_FULL_YEAR = {"effective_from": "2026-01-01", "effective_to": "2026-12-31"}

TEST_DEFAULTS = {
    "FIXED_CONSIDERATION_CENTS": 100000,
    "SSP_CENTS": 100000,
}
