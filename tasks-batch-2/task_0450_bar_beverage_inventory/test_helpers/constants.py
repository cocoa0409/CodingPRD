"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Invoice reconciliation tiers and tax (PRD §3.6)
INVOICE_TIER1_THRESHOLD_CENTS = 30000   # >= 30000 -> 3% discount
INVOICE_TIER2_THRESHOLD_CENTS = 40000   # >= 40000 -> 5% discount (inclusive boundary)
INVOICE_TIER1_DISCOUNT_PCT = 0.03
INVOICE_TIER2_DISCOUNT_PCT = 0.05
INVOICE_TAX_RATE = 0.0875

# Keg yield default line loss (PRD §3.2)
DEFAULT_LINE_LOSS_PCT = 0.05

# Menu engineering popularity factor (PRD §3.4)
POPULARITY_FACTOR = 0.70

# Product field defaults (PRD §3.1)
DEFAULT_CASE_PACK = 1
DEFAULT_DENSITY_G_PER_ML = 1.0
DEFAULT_EMPTY_CONTAINER_WEIGHT_G = 0
DEFAULT_FREIGHT_CENTS = 0

# Test convenience values
TEST_DEFAULTS = {
    "BOTTLE_VOLUME_ML": 750,
    "KEG_HALF_BARREL_ML": 58670,
}
