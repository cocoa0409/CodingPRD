"""Domain thresholds — numeric constants from PRD calculations and global rules."""

# Capacity derating (PRD §2.5): usable = floor(rated * 0.80)
DERATE_PCT = 0.80

# Quote pricing (PRD §3.3)
NIGHT_DEMO_FEE_CENTS = 15000
TAX_RATE = 0.0825
# Volume tiers by total fixture quantity (breakpoints fall into higher tier).
VOLUME_TIERS = [
    (0, 0.00),    # qty < 10
    (10, 0.05),   # 10 <= qty < 25
    (25, 0.10),   # 25 <= qty < 50
    (50, 0.15),   # qty >= 50
]

# Service-plan refund (PRD §3.9)
REFUND_GRACE_DAYS = 30
DAYS_IN_YEAR = 365

# Warranty replacement credit (PRD §3.11)
FULL_WINDOW_MONTHS = 12
MONTH_DAYS = 30  # warranty age uses pinned 30-day months
DEFAULT_WARRANTY_MONTHS = 60

# Time windows (PRD §2.8)
TRANSITION_BUFFER_MIN = 5

# Quote validity (PRD §3.3)
QUOTE_VALIDITY_DAYS = 14

# Logical-clock default (PRD §2.8)
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# A syntactically valid UUID that does not resolve to any entity.
GHOST_UUID = "00000000-0000-4000-8000-000000000000"
