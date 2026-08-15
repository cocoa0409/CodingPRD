"""Domain thresholds and reusable value sets from the PRD's calculations."""

# Logical clock startup default (PRD §2.6).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Exposure tier classification boundaries, integer cents (PRD §3.1).
TIER1_MAX_CENTS = 25_000_000
TIER2_MAX_CENTS = 100_000_000
TIER3_MAX_CENTS = 500_000_000

# Reserve base per tier, integer cents (PRD §3.1).
RESERVE_BASE = {
    "TIER_1": 500_000,
    "TIER_2": 2_500_000,
    "TIER_3": 10_000_000,
    "TIER_4": 50_000_000,
}

# Budget utilization thresholds (PRD §2.9 / §3.4).
UTILIZATION_RESTRICT_THRESHOLD = 90
UTILIZATION_FROZEN_THRESHOLD = 100

# Work-order tiered pricing (PRD §3.6).
WO_TIER_A_GB = 100
WO_TIER_B_GB = 500
WO_DISCOUNT_B_PCT = 80
WO_DISCOUNT_C_PCT = 60

# Custodian escalation cooling period in days (PRD §3.5).
ESCALATION_COOLING_DAYS = 5

# Deadline EXPIRED sweep lag in days (PRD §2.6).
DEADLINE_EXPIRY_LAG_DAYS = 30

# Contingency percentage range for engagements (PRD §3.3).
CONTINGENCY_PCT_MIN = 1
CONTINGENCY_PCT_MAX = 40

# Canonical exposure triplets used by fixtures.
# (low, high, prob) -> expected loss (low+high)*prob//200 = 30,000,000 -> TIER_2.
TIER2_EXPOSURE = (20_000_000, 40_000_000, 100)
# Generic low-exposure triplet -> expected loss 1,500,000 -> TIER_1.
TIER1_EXPOSURE = (1_000_000, 4_000_000, 60)
# A1 dual-variant pair: identical numbers, base vs conservative variants.
VARIANT_EXPOSURE = (1_000_000, 101_000_000, 100)

TEST_DEFAULTS = {
    "FILING_DATE": "2026-07-01",
    "DEADLINE_DUE": "2026-09-01T00:00:00Z",
    "FISCAL_YEAR": 2026,
    "LIFECYCLE_BUDGET_CENTS": 1_000_000_000,
    "FY_BUDGET_CENTS": 500_000_000,
    "RATE_CAP_CENTS": 90_000,
    "PROPOSED_RATE_CENTS": 80_000,
    "SETTLEMENT_EXPIRES_AT": "2026-12-31T00:00:00Z",
}
