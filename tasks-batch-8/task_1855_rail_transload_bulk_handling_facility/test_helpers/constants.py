"""Domain thresholds — numeric constants named by the PRD's calculation rules
(§2.4 logical clock, §2.6 facility config and posture, §3.3 demurrage tiers,
§3.4 switching fees, §3.5 contamination block, §3.7 cleaning fees)."""

# Logical clock default reading before any clock call (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # §2.6 facility config defaults
    "FREE_DEMURRAGE_HOURS": 48,
    "SIT_FREE_DAYS": 2,
    "SWITCH_BUFFER_MINUTES": 30,
    "FREE_SWITCHES_PER_PERIOD": 0,
    # §2.6 posture: count of open incidents at or above this suspends
    "SUSPEND_INCIDENT_COUNT": 3,
    # §3.3 demurrage tiers (integer cents per billable day)
    "TIER1_DAYS": 3,
    "TIER1_RATE": 7500,
    "TIER2_DAYS": 4,
    "TIER2_RATE": 15000,
    "TIER3_RATE": 25000,
    "MINUTES_PER_DAY": 1440,
    # §3.5 contamination block threshold (score must be strictly below)
    "CONTAMINATION_BLOCK_THRESHOLD": 100,
    # §3.4 switching base fees (integer cents per move)
    "BASE_SPOT_FEE": 18500,
    "BASE_PULL_FEE": 20500,
    # §3.7 cleaning fees per wash_type (integer cents per attempt)
    "RINSE_FEE": 250000,
    "DETERGENT_FEE": 600000,
    "STEAM_FEE": 1200000,
    # §3.7 release PULL crew window length in minutes
    "PULL_WINDOW_MINUTES": 30,
}

TEST_DEFAULTS = {
    "SIT_DAILY_RATE_CENTS": 5000,
    "QUANTITY_LOADED_TONS": 40.0,
    "TRUCK_MAX_PAYLOAD_TONS": 40.0,
    "ALLOCATED_CAR_SPOTS": 5,
    "SPOT_CAPACITY": 1,
}
