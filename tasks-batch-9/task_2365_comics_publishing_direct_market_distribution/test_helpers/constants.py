"""Domain thresholds and defaults drawn from the PRD's stated calculations."""

# Final order cut-off derivation and on-sale cadence.
FOC_LEAD_DAYS = 21
ON_SALE_CADENCE_DAYS = 21

# Schedule-health posture thresholds (both inclusive upper bounds).
SLIP_ON_TRACK_DAYS = 7
SLIP_AT_RISK_DAYS = 21

# Retailer-exclusive cover eligibility.
EXCLUSIVE_ELIGIBILITY_UNITS = 10_000
EXCLUSIVE_MIN_RATIO = 50

# Volume discount tiers (inclusive lower bounds on cumulative_units_ytd).
TIER_BASIC_UNITS = 2_500
TIER_CORE_UNITS = 10_000
TIER_PREMIER_UNITS = 25_000

DISCOUNT_PCT = {
    "ENTRY": 0.40,
    "BASIC": 0.45,
    "CORE": 0.50,
    "PREMIER": 0.55,
}

BILLED_FRACTION = {tier: 1.0 - pct for tier, pct in DISCOUNT_PCT.items()}

# Handling fee.
HANDLING_FEE_CENTS = 995
FREE_HANDLING_THRESHOLD_CENTS = 50_000

# Print-run sizing.
OVERPRINT_PCT = 0.08
RESERVE_COPIES = 150
CARTON_MULTIPLE = 250
MIN_FIRST_PRINTING = 500
REORDER_DEMAND_FACTOR = 0.35
MIN_REPRINT = 250

# Royalty accounting.
RETURNS_RESERVE_PCT = 20
CHANNEL_MULTIPLIER_BPS = {
    "PRINT_DM": 10_000,
    "DIGITAL": 20_000,
    "COLLECTED": 12_500,
    "SUBSIDIARY": 40_000,
}
POOL_DENOMINATOR = 100_000_000
CHANNEL_ORDER = ("PRINT_DM", "DIGITAL", "COLLECTED", "SUBSIDIARY")

# Negotiation.
MAX_NEGOTIATION_ROUNDS = 3

# Downstream-edition windows.
DIGITAL_EMBARGO_DAYS = 30
COLLECTED_BLACKOUT_DAYS = 90
REPRINT_COLLECTED_GUARD_DAYS = 60

# Production board.
REQUIRED_CRAFTS = ("SCRIPT", "PENCILS", "INKS", "COLORS", "LETTERS")
ALL_CRAFTS = ("SCRIPT", "PENCILS", "INKS", "COLORS", "LETTERS", "COVER")
LEGAL_INCENTIVE_RATIOS = (10, 25, 50, 100)

# Cascade reason literals.
AUTO_SLIP = "AUTO_SLIP"
AUTO_TITLE_CANCEL = "AUTO_TITLE_CANCEL"

# The logical clock's value until it is ever set.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "CLOCK": DEFAULT_CLOCK,
    "TITLE_NAME": "Nebula Knights",
    "PLANNED_ISSUE_COUNT": 6,
    "ROYALTY_POOL_BPS": 1200,
    "COVER_PARTICIPATION_BPS": 1500,
    "PAGE_COUNT": 22,
    "COVER_PRICE_CENTS": 399,
    "TARGET_ON_SALE_DATE": "2026-10-14",
    "SOLICITATION_MONTH": "2026-08",
    "SUBMISSION_DEADLINE": "2026-08-20",
    "ON_SALE_MONTH": "2026-10",
    "MAX_SLOTS": 5,
    "COPY_TEXT": (
        "Nebula Knights #1 debut: the Knights answer a distress call "
        "from the rim colonies."
    ),
    "COVER_IMAGE_URL": "https://cdn.example.com/nk1.jpg",
}
