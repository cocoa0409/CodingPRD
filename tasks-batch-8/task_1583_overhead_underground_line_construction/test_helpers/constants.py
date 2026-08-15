"""Domain thresholds and shared constants from the PRD.

Numeric rules: PRD §2.7 (rounding), §3.1 (contract percentage defaults),
§3.6 (sixty-minute outage clearance), §3.7 (storm premium multipliers),
§2.5 (logical-clock startup default).
"""

# Contract percentage defaults (PRD §3.1)
DEFAULT_RETAINAGE_PCT = 0.10
DEFAULT_OVERRUN_THRESHOLD_PCT = 1.10
DEFAULT_QUANTITY_CAP_PCT = 1.25

# Storm premium pay (PRD §3.7)
STANDBY_MULT = 0.5
CALLOUT_MULT = 2.0
CALLOUT_MINIMUM_HOURS = 4

# Outage clearance buffer (PRD §3.6)
OUTAGE_BUFFER_MINUTES = 60

# Logical clock (PRD §2.5): startup default before any client sets it.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common working window used across field scenarios: the clock is parked
# mid-day on the first working date so assignment activation succeeds.
FIELD_CLOCK = "2026-08-03T12:00:00Z"
WORK_START = "2026-08-03"
WORK_END = "2026-08-07"

TEST_DEFAULTS = {
    "UTILITY_NAME": "City Power",
    "EFFECTIVE_START": "2026-08-01T00:00:00Z",
    "EFFECTIVE_END": "2026-12-31T00:00:00Z",
    "UNIT_PRICE": 10.00,
    "ESTIMATED_QUANTITY": 100,
    "BASE_RATE_PER_HOUR": 55.00,
    "DAILY_RATE": 120.00,
}
