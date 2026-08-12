"""Domain thresholds and pinned numeric constants from the PRD."""

# Logical clock startup default (PRD: the clock starts at exactly this instant
# before any administrative intervention, and never falls back to wall-clock).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Offer expiry: each offer expires exactly 30 minutes after offered_at.
OFFER_EXPIRY_MINUTES = 30

# Material formula constants (PRD scope section).
SHEET_COVERAGE_SQFT = 32
SQIN_PER_SQFT = 144
TARP_OVERLAP_FACTOR = 1.25

# Hazard weights and band thresholds (PRD safety section).
HAZARD_WEIGHTS = {
    "COLLAPSE": 45,
    "ELECTRICAL": 25,
    "GAS": 20,
    "WATER": 15,
    "ASBESTOS": 10,
}
HAZARD_SCORE_CAP = 100
HAZARD_HIGH_THRESHOLD = 70
HAZARD_MODERATE_THRESHOLD = 30

# Priority multipliers applied to work rates and patrol fees.
PRIORITY_MULTIPLIER = {"P1": 1.50, "P2": 1.25, "P3": 1.00}

# Invoice discount tiers keyed on the pre-discount total.
DISCOUNT_TIER2_MIN_CENTS = 500000   # >= earns 10%
DISCOUNT_TIER1_MIN_CENTS = 200000   # >= earns 5%
DISCOUNT_TIER2_PCT = 0.10
DISCOUNT_TIER1_PCT = 0.05

# FINAL invoice variance cap over the provisional work subtotal.
VARIANCE_CAP_PCT = 0.20

# Service billing.
SECONDS_PER_DAY = 86400

# Pagination defaults (PRD pagination section).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
