"""Domain thresholds — numeric constants from PRD calculations."""

# Loyalty tiers (PRD §3.6): discount fraction keyed off lifetime_booking_count.
LOYALTY_TIERS = [
    (0, 0.00),    # count < 5
    (5, 0.05),    # 5 <= count < 15
    (15, 0.10),   # 15 <= count < 40
    (40, 0.15),   # count >= 40
]
MOVE_OUT_MINIMUM_CENTS = 20000

# Window-fee bands (PRD §3.5).
FREE_CANCEL_HOURS = 48
LATE_CANCEL_HOURS = 12
RESCHEDULE_FEE_CENTS = 1500
LATE_CANCEL_PCT = 0.25
NOSHOW_CANCEL_PCT = 0.50

# Commission split (PRD §3.7).
PAYOUT_PCT = 0.70

# Visit windows (PRD §3.3) in minutes, keyed by home_size.
VISIT_MINUTES = {
    "STUDIO": 90,
    "ONE_BR": 120,
    "TWO_BR": 150,
    "THREE_BR": 180,
    "FOUR_PLUS_BR": 240,
}
TRAVEL_BUFFER_MIN = 30
RECLEAN_WINDOW_HOURS = 72

# A standard rate card used across most fixtures.
STANDARD_BASE_PRICE_CENTS = {
    "STUDIO": 6000,
    "ONE_BR": 8000,
    "TWO_BR": 11000,
    "THREE_BR": 14000,
    "FOUR_PLUS_BR": 18000,
}
STANDARD_DEEP_CLEAN_PCT = 0.50
STANDARD_MOVE_OUT_PCT = 0.75
STANDARD_SUPPLIES_FEE_CENTS = 1500

TEST_POSTAL_CODE = "94110"
