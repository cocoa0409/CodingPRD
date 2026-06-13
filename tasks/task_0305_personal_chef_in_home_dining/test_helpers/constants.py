"""Domain thresholds — numeric constants from the PRD pricing/refund/reliability rules."""

# Labor small-party surcharge (PRD §3.4)
SMALL_PARTY_THRESHOLD = 4       # party_size strictly below this takes the surcharge
SMALL_PARTY_SURCHARGE = 1.20    # per-guest base multiplied by this, rounded half up

# Grocery markup tier selection (PRD §3.4)
TIER1_CEILING = 20000           # subtotal < this -> RATE_LOW_VOLUME
TIER2_CEILING = 50000           # subtotal in [TIER1, TIER2) -> RATE_MID_VOLUME
RATE_LOW_VOLUME = 0.25
RATE_MID_VOLUME = 0.18
RATE_HIGH_VOLUME = 0.12

# Deposit (PRD §3.4)
DEPOSIT_PCT = 0.30

# Cancellation refund lead-time tiers (PRD §3.8)
FULL_REFUND_DAYS = 14           # lead_days >= this -> rate 1.00
HALF_REFUND_DAYS = 7            # lead_days >= this (but < 14) -> rate 0.50

# Chef reliability scoring (PRD §3.7)
BASE_SCORE = 50
COMPLETE_BONUS = 10
DECLINE_PENALTY = -8
CONFIRMED_PROVISIONAL_BONUS = 10
SCORE_FLOOR = 0
SCORE_CEILING = 100

# Chef defaults (PRD §3.1)
DEFAULT_PREP_BUFFER_MINUTES = 90
DEFAULT_MAX_BOOKINGS_PER_DAY = 2

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Canonical "menu A" pricing landmarks used throughout the design indices.
# party 6, base 9000, est ingredient 4000, ZONE_A fee 5000:
#   labor = 54000, est_subtotal = 24000 (MID tier 0.18),
#   est_grocery = 28320, quote = 87320, deposit = 26196.
MENU_A_BASE_PRICE_PER_GUEST_CENTS = 9000
MENU_A_EST_INGREDIENT_PER_GUEST_CENTS = 4000
ZONE_A_TRAVEL_FEE_CENTS = 5000

# A syntactically-valid UUID that is never minted by the server.
NONEXISTENT_BOOKING_ID = "00000000-0000-4000-8000-0000000000ff"
