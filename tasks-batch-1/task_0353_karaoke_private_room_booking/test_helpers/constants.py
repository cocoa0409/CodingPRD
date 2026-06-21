"""Domain thresholds — numeric constants from the PRD pricing/policy narratives.

NON_EXISTENT_UUID comes from the framework; re-exported via the barrel.
"""

# Pricing / time constants (PRD §2.6, §2.9, §3.3, §3.4).
MINUTES_PER_HOUR = 60
OVERAGE_MULTIPLIER = 2.0

# Documented venue policy defaults (PRD §3.1).
VENUE_DEFAULTS = {
    "peak_multiplier": 1.5,
    "deposit_pct": 0.2,
    "cancellation_cutoff_hours": 24,
    "grace_minutes": 15,
    "overage_grace_minutes": 10,
}

# Peak window used across the difficulty/corner setups: 18:00-23:00 local (UTC venue).
PEAK_START_MINUTE = 1080  # 18:00
PEAK_END_MINUTE = 1380    # 23:00

# Common room-size base rates used in the design indices.
BASE_RATE_SMALL_CENTS = 3500
BASE_RATE_MEDIUM_CENTS = 5000
BASE_RATE_LARGE_CENTS = 6000

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
