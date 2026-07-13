"""Domain thresholds and numeric constants from the PRD calculations."""

# Haul-fee schedule (Section 3.6)
HAUL_BASE_FEE_CENTS = 3500
TIER_A_MAX_CF = 100
TIER_A_RATE_CENTS_PER_CF = 40
TIER_B_MAX_CF = 250
TIER_B_RATE_CENTS_PER_CF = 60
TIER_C_RATE_CENTS_PER_CF = 80
ATTENDED_SURCHARGE_CENTS = 2000
DIVERSION_CREDIT_PER_LB_CENTS = 5
DIVERSION_CREDIT_MAX_PCT = 0.30

# Tax-receipt fair-market condition factors (Section 3.6)
CONDITION_FACTOR = {
    "NEW": 1.00,
    "GOOD": 0.70,
    "FAIR": 0.40,
    "POOR": 0.15,
}

# Free-donation / donation volume cap (Section 3.2, Section 3.4)
DONATION_MAX_CF = 50

# Stop-slot travel buffer, minutes each side (Section 3.4)
TRAVEL_BUFFER_MIN = 15

# Pagination (Section 2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Logical-clock startup default (Section 2.9)
CLOCK_START_UTC = "2026-03-01T00:00:00Z"

# Convenient test defaults for route windows / slots on a single service day.
DEFAULT_SERVICE_DATE = "2026-03-15"
DEFAULT_WINDOW_START = "2026-03-15T09:00:00Z"
DEFAULT_WINDOW_END = "2026-03-15T17:00:00Z"
