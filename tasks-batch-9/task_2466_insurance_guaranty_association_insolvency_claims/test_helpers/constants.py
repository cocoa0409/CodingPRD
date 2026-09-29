"""Domain thresholds and shared literals drawn from the PRD's computations."""

# Numeric constants named by the PRD's money computations.
SHORT_RATE_FACTOR = 0.90
MAX_REDISTRIBUTION_ROUNDS = 3
MAX_AGGREGATE_SURCHARGE_BPS = 300
DEFAULT_ANNUAL_CAP_RATE_BPS = 200

# Declared defaults on the statutory coverage configuration row.
DEFAULT_STATUTORY_DEDUCTIBLE_CENTS = 10_000
DEFAULT_NET_WORTH_EXCLUSION_THRESHOLD_CENTS = 2_500_000_000
DEFAULT_COVERS_PUNITIVE_DAMAGES = False
DEFAULT_CAP_ORDER_MODE = "OFFSET_THEN_CAP"

# Pagination contract.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# The logical clock's startup default.
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# The association's own state code.
ASSOCIATION_STATE_CODE = "MI"

# Reusable scenario literals shared by many setups.
DEFAULT_LIQUIDATION_ORDER_DATE = "2026-03-01"
DEFAULT_COVERAGE_TERMINATION_DATE = "2026-03-31"
DEFAULT_PROOF_OF_CLAIM_DEADLINE_UTC = "2027-03-01T00:00:00Z"

PERSONAL_AUTO_CAPS = {
    "per_claim_cap_cents": 3_000_000,
    "per_policy_aggregate_cap_cents": 5_000_000,
    "unearned_premium_cap_cents": 1_000_000,
    "statutory_deductible_cents": 10_000,
    "refund_priority_class": 2,
}

# Fixed opaque actor identifiers used by the segregation-of-duties pairing.
SCREENING_ANALYST_USER_ID = "analyst-1"
SECOND_ANALYST_USER_ID = "analyst-2"
COMMITTEE_OFFICER_USER_ID = "officer-1"

# Deterministic well-formed UUIDs that match no stored row.
UNKNOWN_INSOLVENCY_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_CLAIM_ID = "3f2b9d55-77aa-4c11-8e0d-91b5c2ad4e60"
UNKNOWN_POLICY_ID = "6c1d4e88-0b12-4f33-9a77-5d2e8f0a3b41"
UNKNOWN_GENERIC_ID = "11111111-2222-4333-8444-555555555555"
