"""Domain thresholds — numeric constants from the PRD calculations (PRD §3).

Generic NON_EXISTENT_UUID comes from the framework; only PRD-declared numeric
constants live here.
"""

# Proof validation (PRD §3.3).
VALIDATION_WINDOW_DAYS = 90
AMOUNT_TOLERANCE_CENTS = 500

# Refund depreciation (PRD §3.8).
DECLINING_RATE = 0.97

# Premium refund on early cancellation (PRD §3.9).
SHORT_RATE_PENALTY = 0.10

# Transfer fee (PRD §3.12).
TRANSFER_RATE_YEAR1 = 1500
TRANSFER_RATE_YEAR1_3 = 2500
TRANSFER_RATE_YEAR3_PLUS = 4000
CATEGORY_SURCHARGE_CENTS = 1000
TRANSFER_FEE_FLOOR_CENTS = 1000

# Coverage reconciliation floor (PRD §2.7).
COVERAGE_FLOOR_CENTS = 0

# Claim cooldown (PRD §3.5).
CLAIM_COOLDOWN_DAYS = 30

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
