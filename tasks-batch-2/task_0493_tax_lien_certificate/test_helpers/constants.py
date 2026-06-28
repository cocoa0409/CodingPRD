"""Domain thresholds — numeric constants from PRD interest/accrual rules."""

# Seconds per day used by the floor-day interest accrual (PRD §2.6).
SECONDS_PER_DAY = 86400

# Default county configuration values (PRD §3.1).
DEFAULT_DAY_COUNT_BASIS = 365
DEFAULT_PENALTY_RATE_BPS = 0

# Statutory rate bounds (PRD §3.1).
MIN_INTEREST_RATE_BPS = 1
MAX_INTEREST_RATE_BPS = 5000

# Basis-point denominator: 10,000 bps == 100% (PRD §2.6).
BPS_DENOMINATOR = 10000

# Common starting clock instant (server startup default, PRD §2.4).
SERVER_DEFAULT_CLOCK = "2026-01-01T00:00:00Z"
