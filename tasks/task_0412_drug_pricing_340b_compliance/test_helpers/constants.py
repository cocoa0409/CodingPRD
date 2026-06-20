"""Domain thresholds — numeric constants from PRD calculations (§2.8, §3)."""

# Penny pricing floor (PRD §3.3): when URA >= AMP the ceiling is forced to 1 cent.
PENNY_PRICE_CENTS = 1

# Eligible prescriber relationship types (PRD §3.5 prescriber prong).
ELIGIBLE_PRESCRIBER_TYPES = ["EMPLOYED", "CONTRACTED"]

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
MIN_OFFSET = 0

# A canonical pricing-quarter used across setups.
TEST_QUARTER = "2026Q2"
