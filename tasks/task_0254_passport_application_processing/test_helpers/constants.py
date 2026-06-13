"""Domain thresholds — numeric constants from the PRD fee, risk, SLA, and photo rules."""

# Fee components, in integer cents (PRD 3.5).
FEE = {
    "BOOK_ADULT_CENTS": 13000,
    "BOOK_MINOR_CENTS": 10000,
    "CARD_ADULT_CENTS": 3000,
    "CARD_MINOR_CENTS": 1500,
    "BUNDLE_DISCOUNT_CENTS": 1000,
    "EXECUTION_FEE_CENTS": 3500,
    "EXPEDITE_FEE_CENTS": 6000,
    "URGENT_SURCHARGE_CENTS": 6000,
    "ONE_DAY_DELIVERY_CENTS": 2136,
}

# Common totals used across tests (PRD 3.5).
# Adult NEW BOOK ROUTINE: 13000 base + 3500 execution = 16500.
ADULT_NEW_BOOK_TOTAL = 16500
# Same with an urgent counter appointment booked: + 6000 urgent = 22500.
ADULT_NEW_BOOK_URGENT_TOTAL = 22500

# Verification risk score (PRD 3.6).
RISK = {
    "W_IDENTITY": 0.40,
    "W_CITIZENSHIP": 0.35,
    "W_PHOTO": 0.25,
    "REVIEW_HOLD_THRESHOLD": 50,
}

# SLA processing-target spans, in calendar days (PRD 3.8).
SLA = {
    "ROUTINE_DAYS": 42,
    "EXPEDITE_DAYS": 21,
}

# Photo validation thresholds (PRD 3.3).
PHOTO = {
    "MIN_DIMENSION_PX": 600,
    "RATIO_MIN": 0.98,
    "RATIO_MAX": 1.02,
    "HEAD_FRACTION_MIN": 0.50,
    "HEAD_FRACTION_MAX": 0.69,
}

# Default urgent-travel-counter cleanup buffer (PRD 3.1).
DEFAULT_CLEANUP_BUFFER_MINUTES = 15

# A bare UUID that is never minted by the server (for FK-not-found probes).
UNUSED_UUID = "00000000-0000-4000-8000-000000000000"
UNUSED_UUID_2 = "11111111-1111-4111-8111-111111111111"
