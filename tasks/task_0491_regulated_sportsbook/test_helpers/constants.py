"""Domain thresholds — numeric constants from PRD calculations and global rules."""

# Minimum age in years required to verify KYC (PRD §3.1).
MIN_AGE_YEARS = 21

# Geolocation rules (PRD §3.4).
GEO_TTL_SECONDS = 900          # a geo reading is good for fifteen minutes
MAX_ACCURACY_M = 100           # max tolerated horizontal accuracy radius in meters

# Rolling-window lengths in seconds (PRD §3.3, §3.7).
DAILY_SECONDS = 86_400
WEEKLY_SECONDS = 604_800

# Cash-out book retention factor (PRD §3.9).
CASHOUT_RETENTION = 0.92

# Default logical-clock value at server startup (PRD §2.5).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# Permitted betting jurisdictions (PRD §3.1, §3.4).
PERMITTED_BETTING_STATES = ["NJ", "NY", "PA", "CO", "AZ", "NV"]

# Test-default monetary amounts.
TEST_DEFAULTS = {
    "DEPOSIT_CENTS": 100_000,
    "STAKE_CENTS": 5_000,
}
