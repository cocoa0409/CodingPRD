"""Domain thresholds and shared conventions from the PRD."""

# Season window used across the test suite (183 days -> 27 season weeks).
SEASON_START_DATE = "2026-05-01"
SEASON_END_DATE = "2026-10-31"
SEASON_YEAR = 2026
TOTAL_SEASON_WEEKS = 27

# Logical clock conventions.
CLOCK_ENROLLMENT = "2026-04-15T00:00:00Z"   # before season start
CLOCK_IN_SEASON = "2026-05-18T00:00:00Z"    # inside season window
CLOCK_OFF_SEASON = "2026-11-05T00:00:00Z"   # after season end
SERVER_DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Mondays inside the 2026 season window.
MONDAYS_2026 = [
    "2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25",
    "2026-06-01", "2026-06-08", "2026-06-15",
]

# Zone fee conventions.
OPT_IN_BASE_FEE_CENTS = 12000
UNIVERSAL_BASE_FEE_CENTS = 9000
UNIVERSAL_FLAT_CREDIT_CENTS = 500
DEFAULT_MAX_STRIKES = 3

# Fee schedule (PRD section 3.3).
CART_SURCHARGE_CENTS = {35: 0, 64: 1500, 96: 3000}
EXTRA_CART_FEE_CENTS = 2500
REINSTATEMENT_SURCHARGE_CENTS = 2000
CART_LIMIT_PER_HOUSEHOLD = 2

# Compost yield (PRD section 2.7): each collected pound -> 0.025 gallons.
COMPOST_YIELD_RATIO = 0.5
COMPOST_LBS_PER_GALLON = 20
COMPOST_GALLONS_PER_LB = 0.025

# Route capacity (PRD section 3.4).
AVG_TICKET_WEIGHT_LBS = 200

# Facility delivery bay window buffer (PRD section 3.8).
DELIVERY_WINDOW_BUFFER_MINUTES = 30

# Cart retrieval finalization lag (PRD section 3.3).
CART_RETRIEVAL_DAYS_AFTER_SEASON = 14
