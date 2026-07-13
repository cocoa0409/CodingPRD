"""Domain thresholds — numeric constants from PRD calculations."""

# Booking payout (PRD 3.6): commission and processing fee are each rounded
# half-up independently before being subtracted from the price.
COMMISSION_PCT = 0.15
PROCESSING_PCT = 0.029
FLAT_FEE_CENTS = 30

# Demand pricing (PRD 3.3): the demand multiplier is 1.0 below the threshold.
NORMAL_MULTIPLIER = 1.0

# Calendar rule (PRD 3.5): travel buffer around each confirmed booking.
BUFFER_MINUTES = 30

# Logical clock (PRD 2.6): process-startup default instant.
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_LEAD_PRICE_CENTS": 5000,
    "MAX_LEADS_PER_REQUEST": 2,
    "DEMAND_HIGH_THRESHOLD": 5,
    "DEMAND_MULTIPLIER_HIGH": 1.5,
    "REFUND_WINDOW_HOURS": 24,
    "MIN_RATING_TO_RECEIVE_LEADS": 0.0,
    "ZIP": "94016",
    "WALLET": 20000,
}
