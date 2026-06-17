"""Domain thresholds — numeric constants from the PRD calculations and defaults.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Cancellation tier constants (PRD §3.7).
CANCELLATION = {
    "TIER1_LEAD_MIN": 60,
    "TIER1_PCT": 25,
    "TIER2_PCT": 50,
}

# Flight delay threshold (PRD §3.6): strictly greater than 15 minutes -> DELAYED.
FLIGHT_DELAY_THRESHOLD_MIN = 15

# Server-applied defaults for optional input fields (PRD §3.1).
DEFAULTS = {
    "NEGOTIATED_DISCOUNT_PCT": 0,
    "DEFAULT_GRATUITY_PCT": 20,
    "CANCELLATION_GRACE_MINUTES": 120,
    "INCLUDED_WAIT_MINUTES": 15,
    "TURNAROUND_MINUTES": 30,
    "REST_BUFFER_MINUTES": 20,
    "TOLLS_CENTS": 0,
    "ESTIMATED_MILES": 0,
    "CHARTER_HOURS": 0,
    "MEET_AND_GREET": False,
}

# Percent input ranges (PRD §3.1).
RANGES = {
    "NEGOTIATED_DISCOUNT_PCT": (0, 40),
    "GRATUITY_PCT": (0, 30),
    "PAYOUT_SHARE_PCT": (0, 90),
}

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "LIMIT_DEFAULT": 10,
    "LIMIT_MIN": 1,
    "LIMIT_MAX": 100,
    "OFFSET_DEFAULT": 0,
}
