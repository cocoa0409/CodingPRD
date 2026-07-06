"""Domain thresholds — numeric constants drawn from the PRD calculation rules
(§2.5, §2.6, §3.1, §3.3, §3.7, §3.8)."""

# Planner-fee tiers (PRD §3.1)
PLANNER_FEE = {
    "FLAT_DAY_OF_CENTS": 250_000,
    "BASE_PARTIAL_CENTS": 400_000,
    "PER_GUEST_CENTS": 5_000,
    "BASE_FULL_CENTS": 800_000,
    "FULL_TIER_1_CENTS": 5_000_000,     # budget <= this -> 12%
    "FULL_TIER_2_CENTS": 15_000_000,    # budget <= this -> 15% ; above -> 18%
    "FULL_RATE_1": 0.12,
    "FULL_RATE_2": 0.15,
    "FULL_RATE_3": 0.18,
}

# Vendor deposit / balance split & deposits-due roll-up (PRD §3.3)
DEPOSIT_RATE = 0.30

# Cancellation-fee tiers (PRD §3.8)
CANCELLATION = {
    "FAR_DAYS": 90,     # >= 90 days out -> 25%
    "NEAR_DAYS": 30,    # >= 30 and < 90 -> 50% ; < 30 -> 100%
    "RATE_FAR": 0.25,
    "RATE_NEAR": 0.50,
    "RATE_IMMINENT": 1.00,
}

# Staff double-booking rest buffer (PRD §3.7)
STAFF_BUFFER_MIN = 30

# The server's startup logical-clock value (PRD §2.6).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Convenient defaults used by tests/fixtures.
TEST_DEFAULTS = {
    "EVENT_DATE": "2026-09-15T00:00:00Z",
    "COI_EXPIRY_FAR": "2027-01-01T00:00:00Z",
}
