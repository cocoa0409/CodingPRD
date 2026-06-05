"""Domain thresholds — numeric constants stated in the PRD."""

# PRD §3.1 — Statute of Limitations years per jurisdiction.
STATUTE_YEARS = {
    "CA": 2,
    "NY": 2,
    "TX": 2,
    "FL": 4,
    "IL": 2,
}

# PRD §3.7 — Contingency-fee rates.
PRE_SUIT_RATE = 0.3333
POST_SUIT_RATE = 0.40

# PRD §3.4 — Demand-letter pricing constants.
FUTURE_MED_PV_FACTOR = 0.85
TIER_LOW_CENTS = 500_000  # $5,000 lower tier boundary
TIER_HIGH_CENTS = 5_000_000  # $50,000 upper tier boundary
BUFFER_RATE_LOW = 0.20
BUFFER_RATE_MID = 0.15
BUFFER_RATE_HIGH = 0.10

# PRD §3.3 — Jurisdictional damages cap for PAIN_SUFFERING (CA/FL).
PAIN_SUFFERING_CAP_CENTS_CA_FL = 25_000_000  # $250,000

# PRD §3.5 — Settlement offer expiration.
OFFER_EXPIRY_DAYS = 30

# PRD §3.8 — Court-event scheduling.
COURT_EVENT_BUFFER_HOURS = 24
COURT_EVENT_MAX_DURATION_MINUTES = 600

# PRD §3.4 — Pain multiplier range.
PAIN_MULTIPLIER_MIN = 1.0
PAIN_MULTIPLIER_MAX = 5.0

# PRD §2.3 — Pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
