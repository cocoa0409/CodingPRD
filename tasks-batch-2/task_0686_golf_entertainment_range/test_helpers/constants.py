"""Domain thresholds — numeric constants from the PRD calculations and rules.

NON_EXISTENT_UUID comes from the framework. A well-formed but unused UUID is
provided here for not-found tests that need a syntactically valid id.
"""

# A syntactically valid UUID that resolves to nothing (for ERR_NOT_FOUND tests).
RANDOM_UUID = "00000000-0000-4000-8000-000000000000"

# Logical-clock default at server startup (PRD §2.9).
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"

# Dynamic bay price (PRD §3.3).
BAND_MULTIPLIERS = {"TWILIGHT": 0.80, "OFFPEAK": 1.00, "PEAK": 1.60}
DAY_FACTORS = {"WEEKDAY": 1.00, "WEEKEND": 1.25}
MULT_FLOOR = 0.80
MULT_CEIL = 2.00
TIER_DISCOUNT_PCT = {"STANDARD": 0.00, "GOLD": 0.10, "PLATINUM": 0.15}

# F&B tab totals (PRD §3.9).
GRATUITY_PCT = 0.18
TAX_PCT = 0.0825

# Loyalty earn (PRD §3.7).
POINTS_PER_CENT_DIVISOR = 100
TIER_MULTIPLIER = {"STANDARD": 1.0, "GOLD": 1.25, "PLATINUM": 1.5}

# Scoring streak bonus (PRD §3.6).
STREAK_LEN = 5
STREAK_MIN_POINTS = 10
STREAK_BONUS = 25

# No-show / late-cancel (PRD §3.4).
NO_SHOW_PCT = 0.50
LATE_CANCEL_WINDOW_MINUTES = 120

# Time-to-live windows (PRD §3.3 / §3.5).
HOLD_TTL_MINUTES = 30
QUEUE_TTL_MINUTES = 60

# Venue defaults (PRD §3.1).
DEFAULT_BASE_RATE_CENTS = 2500
DEFAULT_PEAK_DEMAND_FACTOR = 1.0
PEAK_DEMAND_FACTOR_MIN = 0.5
PEAK_DEMAND_FACTOR_MAX = 1.5

# Event package defaults (PRD §3.10).
DEFAULT_BAY_BLOCK_CENTS = 15000
DEFAULT_DEPOSIT_CENTS = 0

# Pagination bounds (PRD §2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}
