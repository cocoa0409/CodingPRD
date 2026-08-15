"""Domain thresholds — numeric constants named by the PRD (§3.3–§3.7)."""

# PRD §3.3: action-tiered labor rates in cents per hour.
LABOR_RATE_CENTS_PER_HOUR = {
    "REGRIND": 8_500,
    "CUT_NEW": 14_200,
    "REPLACE_OEM": 6_000,
    "REUSE_AS_IS": 2_500,
}
RUSH_MULTIPLIER = 1.25

# PRD §3.4: assembly tolerance band (inclusive) and clearance ceiling.
BACKLASH_MIN_MM = 0.08
BACKLASH_MAX_MM = 0.18
CLEARANCE_MAX_MM = 0.05

# PRD §3.4: run-in certification thresholds.
RUN_IN_REQUIRED_MINUTES = 120
RUN_IN_TEMP_MAX_C = 95.0
RUN_IN_VIB_MAX_MM_S = 4.5
RUN_IN_PARTICLE_MAX = 3_200

# PRD §3.5: freight pricing and rigging bay.
FREIGHT_BASE_UP_TO_500KG_CENTS = 45_000
FREIGHT_BASE_UP_TO_2000KG_CENTS = 120_000
FREIGHT_OVERWEIGHT_BLOCK_KG = 500
FREIGHT_OVERWEIGHT_BLOCK_CENTS = 18_000
RIGGING_HOURLY_CENTS = 9_500
RIGGING_BUFFER_HOURS = 2

# PRD §3.7: warranty dual-basis limits.
WARRANTY_HOURS_LIMIT = 2_000
WARRANTY_CALENDAR_DAYS = 365

# PRD §2.8: logical clock startup default.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 90_000_000,
    "QUOTED_ESTIMATE_CENTS": 100_000,
}
