"""Domain thresholds and defaults — numeric constants from the PRD."""

# Logical clock
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Screening thresholds (PRD §3.5)
INCOME_MULTIPLIER = 3
CREDIT_AUTO_APPROVE = 700
CREDIT_CONDITION_MIN = 620

# Deposit multiples (PRD §3.5)
STANDARD_DEPOSIT_MONTHS = 1
CONDITIONAL_DEPOSIT_MONTHS = 2

# Waitlist offer window (PRD §3.4)
OFFER_WINDOW_HOURS = 72

# Lease signing window (PRD §3.6)
SIGNING_WINDOW_HOURS = 48

# Rent override floor (PRD §3.6): override must reach 80% of the computed rent
OVERRIDE_FLOOR_PCT = 0.8

# Property configuration defaults (PRD §3.1)
PROPERTY_DEFAULTS = {
    "response_time_target_minutes": 60,
    "tour_buffer_minutes": 15,
    "self_guided_window_minutes": 60,
    "max_moveins_per_day": 2,
    "utility_transfer_required": True,
    "prorate_method": "CALENDAR",
    "required_addenda": [],
}

# Agent defaults (PRD §3.1)
AGENT_DEFAULTS = {
    "max_concurrent_tours": 1,
    "active": True,
}

# Pricing offer defaults (PRD §3.2)
OFFER_DEFAULTS = {
    "concession_type": "NONE",
    "concession_value": 0,
    "lease_term_months": 12,
}

# Common test values
TEST_DEFAULTS = {
    "BASE_RENT_CENTS": 200000,
    "TOTAL_UNITS": 2,
    "ANNUAL_INCOME_CENTS": 9000000,   # comfortably above 3x12x200000 = 7200000
    "CREDIT_SCORE": 750,
    "OFFER_WINDOW_START": "2026-08-01T00:00:00Z",
    "OFFER_WINDOW_END": "2026-09-01T00:00:00Z",
    "TOUR_START": "2026-08-10T10:00:00Z",
    "TOUR_END": "2026-08-10T11:00:00Z",
    "MOVE_IN_DATE": "2026-08-20T00:00:00Z",
}
