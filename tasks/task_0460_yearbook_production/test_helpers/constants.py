"""Domain thresholds — numeric constants from the Yearbook Production PRD (§2.7, §3.5, §3.7)."""

# Ad pricing list-price tiers, cents (PRD §3.5).
AD_SIZE_PRICE_CENTS = {
    "FULL": 40000,
    "HALF": 24000,
    "QUARTER": 14000,
}

# Pre-sale pricing (PRD §3.5).
EARLY_BASE_CENTS = 6500
STANDARD_BASE_CENTS = 8000
STAMP_FEE_CENTS = 500
BULK_QTY_THRESHOLD = 5
BULK_DISCOUNT_PCT = 0.10

# Production cost (PRD §3.7).
BASE_PAGE_ALLOWANCE = 96
PAGES_PER_SIGNATURE = 4
SIGNATURE_SURCHARGE_CENTS = 800

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Common test window boundaries.
PRESALE_OPEN_ISO = "2026-01-01T00:00:00Z"
PRESALE_CLOSE_ISO = "2026-03-01T00:00:00Z"
