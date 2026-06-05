"""Domain thresholds — numeric constants from PRD calculations."""

# Sliding-scale federal poverty base (PRD §3.2)
FPL_BASE_CENTS = 15_080_000        # one-person federal poverty line (annual, cents)
FPL_PER_PERSON_CENTS = 5_320_000   # incremental per additional household member

# Sibling discount (PRD §3.5)
SIBLING_DISCOUNT_PCT = 10

# Waitlist offer time-to-live (PRD §3.3)
WAITLIST_OFFER_TTL_HOURS = 48

# CACFP per-meal reimbursement rates in cents (PRD §3.6)
CACFP_RATES = {
    "TIER_I": {"breakfast": 240, "lunch": 449, "snack": 119},
    "TIER_II": {"breakfast": 90, "lunch": 271, "snack": 33},
}

# Late-pickup defaults (PRD §3.1)
DEFAULT_LATE_GRACE_MINUTES = 5
DEFAULT_LATE_FEE_PER_BLOCK_CENTS = 1500
DEFAULT_LATE_BLOCK_MINUTES = 15

# Sliding-scale sentinel for the FULL_PAY catch-all row (PRD §3.1)
FULL_PAY_SENTINEL = 999999

TEST_DEFAULTS = {
    "BASE_TUITION_CENTS": 120000,
    "LICENSED_CAPACITY": 5,
}
