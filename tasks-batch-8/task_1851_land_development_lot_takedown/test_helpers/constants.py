"""Domain thresholds — numeric constants from the PRD's business rules."""

# Logical clock (PRD §2.5)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Contingency deadlines used across fixtures (PRD §3.1)
DEFAULT_CONTINGENCY_END = "2027-01-01T00:00:00Z"

# Bond requirement (PRD §3.3): estimate or awarded bid increased by ten percent
# (11000 basis points over ten thousand), rounded half-up to whole cents.
BOND_MULTIPLIER_BP = 11000

# Draw disbursement (PRD §3.6): five-percent retainage rounded first from the
# gross; half-percent fee rounded second from the post-retainage base.
RETAINAGE_BP = 500
DRAW_FEE_BP = 50

# Lot pricing engine (PRD §3.4): quarterly compounding escalator, cap in basis
# points of base, volume discount tiers on closed-lot count.
VOLUME_TIER_1_MIN_CLOSED = 5
VOLUME_TIER_1_DISCOUNT_BP = 250
VOLUME_TIER_2_MIN_CLOSED = 10
VOLUME_TIER_2_DISCOUNT_BP = 500

# Absorption forecasting (PRD §3.8)
PHASE_LEAD_MONTHS = 6
TRAILING_W1 = 0.5
TRAILING_W2 = 0.3
TRAILING_W3 = 0.2

# HOA control transfer (PRD §3.8): default threshold 7500 bp (75%).
DEFAULT_CONTROL_TRANSFER_PCT_BP = 7500
MIN_SEATED_BOARD = 3

# Impact fee indexation (PRD §3.9): three-percent annual indexation compounded
# from the 2024-01-01 ordinance epoch over type-specific base fees.
ORDINANCE_EPOCH = "2024-01-01"
IMPACT_INDEX_BP = 300
IMPACT_BASE_FEE_CENTS = {"WATER": 250000, "SEWER": 300000, "ELECTRIC": 175000}

# Bond reduction gates (PRD §3.3): halves expressed as 5000 bp over 10000.
BOND_REDUCE_LOAN_HALF_BP = 5000
BOND_REDUCE_POSTED_HALF_BP = 5000

# Shared fixture money geometry: estimate 10000000 -> provisional 11000000;
# awarded bid 9000000 -> final requirement 9900000 (PRD §3.3 arithmetic).
TEST_DEFAULTS = {
    "PARCEL_NAME": "Test Parcel",
    "COUNTY": "Travis",
    "EARNEST_MONEY_CENTS": 500000,
    "ENGINEER_ESTIMATE_CENTS": 10000000,
    "AWARDED_BID_CENTS": 9000000,
    "POSTED_BOND_CENTS": 9900000,
    "BASE_LOT_PRICE_CENTS": 5000000,
    "ESCALATOR_RATE_BP_PER_QUARTER": 300,
    "PRICE_CAP_BP": 12000,
    "MIN_LOTS_PER_QUARTER": 1,
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "COMMITMENT_AMOUNT_CENTS": 50000000,
    "RELEASE_PRICE_FLOOR_BP": 8000,
    "SELLING_WINDOW_START": "2026-09-01T00:00:00Z",
    "SELLING_WINDOW_END": "2027-03-01T00:00:00Z",
}
