"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Tiered daily hire rate breakpoints and factors (PRD §3.4).
TIER1_QTY = 10
TIER1_FACTOR = 0.90
TIER2_QTY = 50
TIER2_FACTOR = 0.80

# One logical day, in seconds (PRD §3.4, §3.6).
DAY_SECONDS = 86400

# Demand forecast blend (PRD §3.10).
LOOKBACK_DAYS = 30
ISSUANCE_WEIGHT = 0.70
HIRE_WEIGHT = 0.30

# Policy governance defaults (PRD §3.1).
DEFAULT_EQUITY_WARN_THRESHOLD = 200
DEFAULT_VOUCHER_EXPIRY_DAYS = 90
DEFAULT_AUDIT_MIN_INTERVAL_DAYS = 28
DEFAULT_USEFUL_LIFE_DAYS = 1825
DEFAULT_CURRENCY = "USD"

# Logical-clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"


def tiered_daily_rate(n: int, base_daily_rate_cents: int) -> int:
    """Tiered daily rate for an asset count (PRD §3.4): floored once per tier."""
    import math

    if n >= TIER2_QTY:
        return math.floor(base_daily_rate_cents * TIER2_FACTOR)
    if n >= TIER1_QTY:
        return math.floor(base_daily_rate_cents * TIER1_FACTOR)
    return base_daily_rate_cents
