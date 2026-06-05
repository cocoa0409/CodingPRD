"""Domain thresholds — numeric constants from the PRD calculation narratives."""

# Multi-pet discount (PRD 3.1): threshold is two active policies; discount 1000 bps.
MULTI_PET_THRESHOLD = 2
MULTI_PET_DISCOUNT_BPS = 1000

# Flat Wellness rider premium added per rider-bearing policy (PRD 3.1).
WELLNESS_RIDER_PREMIUM_CENTS = 1500

# Per-year Wellness allowance bucket (PRD 3.7).
WELLNESS_ALLOWANCE_CENTS = 30000

# OCR mismatch tolerance in basis points (PRD 3.5).
OCR_MISMATCH_TOLERANCE_BPS = 500

# Default waiting period when omitted (PRD 3.2).
DEFAULT_WAITING_PERIOD_DAYS = 14

# Basis-point divisor.
BPS_DIVISOR = 10000
