"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Pregnancy-check window: a service's confirm_due_at = service_date + 45 days (PRD §3.5).
PREG_CHECK_WINDOW_DAYS = 45

# Voluntary waiting period: a new service must be >= 30 days from each prior
# non-voided service on the same animal (PRD §3.5).
VWP_DAYS = 30

# Standard lactation length for the 305-day projection (PRD §3.4).
STANDARD_LACTATION_DAYS = 305

# Milk-check settlement constants (PRD §3.8).
OTHER_SOLIDS_PCT = 5.7          # fixed other-solids percent applied per record
SCC_BASE_THOUSANDS = 350        # somatic-cell baseline (in thousands)
SCC_RATE_PER_1000_PER_CWT = 0.0005

# Herd milk-quality bands from the just-finalized weighted SCC (PRD §3.8).
SCC_GOOD_MAX = 200      # <= 200 (thousands) => GOOD
SCC_WARNING_MAX = 400   # 201..400 => WARNING ; > 400 => PENALIZED

# Default server logical-clock instant on startup (PRD §2.4).
DEFAULT_CLOCK_UTC = "2026-01-01T00:00:00Z"

# Shared price-sheet rates used across pinned milk-check fixtures.
DEFAULT_PRICE_SHEET = {
    "fat_price_per_lb": 2.805,
    "protein_price_per_lb": 3.515,
    "other_solids_price_per_lb": 0.405,
    "ppd_per_cwt": 1.205,
    "advance_rate_per_cwt": 16.00,
    "hauling_rate_per_cwt": 0.85,
}
