"""Domain thresholds — numeric constants from the PRD's calculation narratives (§3)."""

# Basis-point denominator used across commission, P&H, and residual math (PRD §2.7).
BPS_DENOMINATOR = 10000

# SAG pension-and-health rate: 1850 bps = 18.5% (PRD §3.8).
SAG_PH_BPS = 1850

# Maximum deal-memo negotiation exchanges; ceiling of eight (PRD §3.5).
MAX_ROUNDS = 8

# Casting director calendar buffer between adjacent slots: 15 minutes (PRD §3.3).
SLOT_BUFFER_MINUTES = 15

# Residual media multipliers in basis points, keyed by casting call media_type (PRD §3.9).
MEDIA_MULTIPLIER_BPS = {
    "BROADCAST_TV": 3000,
    "CABLE": 2000,
    "STREAMING": 1500,
    "PRINT": 1000,
    "DIGITAL": 1200,
}

# Residual period-tier multipliers in basis points by 1-based period_index (PRD §3.9).
# 1 -> 100%, 2 -> 75%, 3 -> 50%, 4+ -> flat 25%.
PERIOD_TIER_BPS = {1: 10000, 2: 7500, 3: 5000}
PERIOD_TIER_BPS_DEFAULT = 2500  # period_index >= 4

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Test defaults reused across fixtures.
TEST_DEFAULTS = {
    "COMMISSION_RATE_BPS": 1000,   # 10%
    "DAY_RATE_CENTS": 200000,
    "SCALE_RATE_CENTS": 100000,
}
