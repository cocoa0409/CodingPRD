"""Domain thresholds — numeric constants drawn from the PRD's calculations (§3)."""

# Pricing (§3.2)
PROCESSING_FEE_RATE = 0.029
MAX_DISCOUNT_PCT = 0.20
PROMO_TABLE = {"SPRING10": 0.10, "WELCOME05": 0.05}

# Refund / deferral (§3.4)
CANCELLATION_FEE_RATE = 0.15
DEFERRAL_FEE_CENTS = 1500

# Waitlist (§3.3)
OFFER_TTL_HOURS = 24

# Bib assignment (§3.6)
BIB_START_NUMBER = 100

# Canonical timeline used across fixtures.
OPENS_UTC = "2026-01-01T00:00:00Z"
CLOSES_UTC = "2026-07-01T00:00:00Z"
RACE_DATE_UTC = "2026-07-05T00:00:00Z"
TIER_EARLY_FROM = "2026-01-01T00:00:00Z"
TIER_REGULAR_FROM = "2026-05-01T00:00:00Z"
TIER_LATE_FROM = "2026-06-15T00:00:00Z"
CLOCK_REGULAR = "2026-06-09T00:00:00Z"   # active tier == REGULAR
CLOCK_LATE = "2026-06-16T00:00:00Z"      # active tier == LATE

# Common pricing figures used as expected values (REGULAR base 5500, party 1, no promo):
#   discount 0; processing fee ceil(5500*0.029)=160; amount 5660.
REGULAR_BASE_CENTS = 5500
