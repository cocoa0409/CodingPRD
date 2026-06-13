"""Domain thresholds — numeric constants from the CGL PRD calculations."""

# Premium rating: rate is cents per $1,000 of basis; floor(basis/1000) BEFORE multiply (PRD §2.9).
BASIS_DIVISOR = 1000

# Posture impairment: IMPAIRED when a bucket's remaining <= floor(limit * 1/4) (PRD §3.6).
IMPAIRED_FRACTION_NUM = 1
IMPAIRED_FRACTION_DEN = 4

# Default insurer audit waiver threshold (PRD §3.1): 50000 cents.
DEFAULT_AUDIT_WAIVER_THRESHOLD_CENTS = 50000

# Insurer business clock default at creation (PRD §2.5).
DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"

# Standard baseline policy parameters used across the design indices.
BASELINE_POLICY = {
    "effective_date": "2026-01-01T00:00:00.000Z",
    "expiration_date": "2027-01-01T00:00:00.000Z",
    "each_occurrence_limit_cents": 100000000,      # $1M
    "general_aggregate_limit_cents": 200000000,    # $2M
    "products_aggregate_limit_cents": 100000000,   # $1M
    "premium_basis": "PAYROLL",
    "rate_per_unit_cents": 300,                     # 300 c / $1,000
    "minimum_premium_cents": 100000,               # $1,000 floor
    "estimated_exposure_units": 1000000,           # $1,000,000 -> 300000c estimated premium
}
