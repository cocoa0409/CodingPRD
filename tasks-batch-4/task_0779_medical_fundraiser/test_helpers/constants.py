"""Domain thresholds — numeric constants from PRD calculations (§2.5, §2.9, §3.4, §3.7).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Donation charge breakdown (PRD §3.4)
PROCESSING_RATE = 0.029
PROCESSING_FIXED_CENTS = 30

# Chargeback reserve (PRD §2.5)
RESERVE_RATE = 0.05

# Donation minimum (PRD §3.4)
MIN_DONATION_CENTS = 100

# Organizer risk scoring (PRD §2.9)
W_DISPUTE = 15
W_REFUND = 50
UNVERIFIED_PENALTY = 20
SCORE_MAX = 100

# Beneficiary payout cooldown (PRD §3.7)
COOLDOWN_HOURS = 24

# Convenient test defaults
TEST_DEFAULTS = {
    "GOAL_CENTS": 500_000,
    "STRIPE_ACCOUNT_REF": "acct_test",
    "SERVER_CLOCK_DEFAULT": "2026-03-01T00:00:00Z",
}
