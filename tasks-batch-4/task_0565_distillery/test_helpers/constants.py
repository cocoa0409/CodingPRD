"""Domain thresholds — numeric constants from the PRD workflows and arithmetic."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Gauging (PRD 3.2 / 2.6)
SPECIFIC_WEIGHT_LBS_PER_GALLON = 7.28
PROOF_DIVISOR = 100

# Angel's share (PRD 3.3)
ANGEL_SHARE_ANNUAL_RATE = 0.05

# Bottling proof gallons (PRD 3.5)
ML_PER_GALLON = 3785.411784

# CBMA excise tiers (PRD 2.6 / 3.6)
CBMA_TIER_LIMIT_PG = 100000
CBMA_REDUCED_RATE_CENTS = 270
STANDARD_RATE_CENTS = 1350

# Order pricing (PRD 3.8)
COCKTAIL_SURCHARGE_CENTS = 1200

# Tasting room (PRD 3.9)
TOUR_BUFFER_MINUTES = 30
TASTING_ROOM_CAPACITY = 20

# Logical clock (PRD 2.5)
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
