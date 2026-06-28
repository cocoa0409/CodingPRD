"""Domain thresholds — numeric constants from PRD pricing/settlement rules."""

# Class surcharges (PRD §3.8): added to monthly fee (MONTHLY) or daily rate (DAILY).
SURCHARGE = {
    "STANDARD": 0,
    "EBIKE": 2000,
    "CARGO_EBIKE": 4000,
}

# Tiered daily-rate breakpoints (PRD §3.8).
TIER1_DAYS = 6          # days 1..6 bill the full effective daily amount
TIER2_LAST_DAY = 29     # days 7..29 bill effective_daily * 0.85
TIER2_RATE = 0.85
TIER3_RATE = 0.70       # days 30+ bill effective_daily * 0.70
CYCLE_DAYS = 30         # one billing cycle is 30 days

# Buyout equity decay (PRD §3.8).
EQUITY_PCT_PER_CYCLE = 0.03
EQUITY_CAP_PCT = 0.60

# Late fee (PRD §3.9).
LATE_FEE_PER_DAY_CENTS = 1500

# Fleet invoice volume discount (PRD §3.11).
VOLUME_THRESHOLD = 5
VOLUME_DISCOUNT_PCT = 0.10

# Coverage caps (PRD §3.10).
THEFT_CAP_PCT = 1.00
DAMAGE_CAP_PCT = 0.40

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Server startup logical-clock default (PRD §2.4).
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"
