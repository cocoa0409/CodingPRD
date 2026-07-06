"""Domain thresholds — numeric constants from the RIA Practice PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Conversion / proration constants (PRD §2.9, §3.4).
DAYS_PER_YEAR = 365
BPS_DENOMINATOR = 10000      # bps -> fraction divisor
BPS_PER_PCT = 100            # pct -> bps
BPS_FULL = 10000             # 10000 bps == 100%

# Clock startup default (PRD §2.4): before any clock-setting call the clock reads
# exactly this default.
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10

# A fabricated UUID guaranteed not to resolve to any entity.
FABRICATED_UUID = "00000000-0000-4000-8000-000000000000"

# Standard three-tier fee schedule used across many fee tests (per the design
# index): <=$1.0M @ 1.00%, <=$5.0M @ 0.75%, rest @ 0.50%, minimum $1,000.00.
STANDARD_TIERS = [
    {"upper_bound_cents": 100000000, "annual_rate_bps": 100},
    {"upper_bound_cents": 500000000, "annual_rate_bps": 75},
    {"upper_bound_cents": None, "annual_rate_bps": 50},
]
STANDARD_MINIMUM_ANNUAL_FEE_CENTS = 100000

# A single open-ended flat tier used where the fee value is incidental.
FLAT_TIERS = [{"upper_bound_cents": None, "annual_rate_bps": 100}]
