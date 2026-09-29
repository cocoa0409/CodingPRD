"""Numeric thresholds and canonical test data drawn from the PRD's own formulas
and worked examples."""

from decimal import ROUND_HALF_UP, Decimal

# ─── Logical clock ────────────────────────────────────
CLOCK_START = "2026-08-01T00:00:00Z"

# ─── Buyer premium (flat tiers, not marginal) ─────────
PREMIUM_TIER_1_MAX_CENTS = 1_000_000
PREMIUM_TIER_2_MAX_CENTS = 2_500_000
PREMIUM_TIER_1_BPS = 1400
PREMIUM_TIER_2_BPS = 1200
PREMIUM_TIER_3_BPS = 1000

# ─── Freight ──────────────────────────────────────────
UNITS_PER_PALLET = 200
FREIGHT_CENTS_PER_PALLET = 8500

# ─── Payment / pickup terms ───────────────────────────
PAYMENT_TERM_DAYS = 3
PICKUP_DEADLINE_DAYS = 10
CLAIM_WINDOW_DAYS = 5
LATE_FEE_BPS = 150

# ─── Commission tiers ─────────────────────────────────
PREFERRED_RECOVERY_THRESHOLD = 0.2500
TIER_PREFERRED_BPS = 1500
TIER_STANDARD_BPS = 2000
TIER_PROBATION_BPS = 2500

# ─── Manifest accuracy ────────────────────────────────
PROBATION_ACCURACY_THRESHOLD = 0.850
SHORTAGE_TOLERANCE_FRACTIONS = {
    "NEW_OVERSTOCK": 0.01,
    "CUSTOMER_RETURNS": 0.03,
    "SALVAGE": 0.08,
}

# ─── Bidding / negotiation ────────────────────────────
DEFAULT_BID_INCREMENT_CENTS = 100_000
SNIPE_WINDOW_SECONDS = 120
EXTENSION_MINUTES = 5
MAX_EXTENSIONS = 3
OFFER_TTL_HOURS = 48
MAX_NEGOTIATION_ROUNDS = 4

# ─── Claims ───────────────────────────────────────────
MIN_EVIDENCE_ITEMS = 2
MAX_EVIDENCE_REQUESTS = 2

# ─── Pagination ───────────────────────────────────────
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ─── Warehouses ───────────────────────────────────────
DEFAULT_TURNAROUND_BUFFER_MINUTES = 15

# ─── Canonical reference data used across the suite ───
CANONICAL_SELLER_TAX_ID = "S-1001"
CANONICAL_BUYER_TAX_ID = "B-2001"
SECOND_BUYER_TAX_ID = "B-2002"
CANONICAL_SCAC_CODE = "KEYF"
CANONICAL_CREDIT_LIMIT_CENTS = 10_000_000

# The PRD's canonical 400-unit CUSTOMER_RETURNS lot: 100 x 40000 + 300 x 20000
# gives declared_unit_count 400 and declared_retail_value_cents 10000000.
CANONICAL_LOT_LINES = [
    {"sku": "APP-RET-0001", "unit_count": 100, "unit_retail_cents": 40_000,
     "declared_condition": "USED_GOOD"},
    {"sku": "APP-RET-0002", "unit_count": 300, "unit_retail_cents": 20_000,
     "declared_condition": "USED_GOOD"},
]

# A single-line 50 x 20000 lot: 1 pallet, declared_retail_value_cents 1000000.
SMALL_LOT_LINES = [
    {"sku": "OVR-NEW-0001", "unit_count": 50, "unit_retail_cents": 20_000,
     "declared_condition": "NEW"},
]

# Auction shape used by most bidding scenarios.
AUCTION_OPENING_BID_CENTS = 1_000_000
AUCTION_RESERVE_PRICE_CENTS = 2_700_000
AUCTION_WINDOW_START = "2026-08-05T00:00:00Z"
AUCTION_WINDOW_END = "2026-08-12T00:00:00Z"
LONG_WINDOW_END = "2026-08-20T00:00:00Z"
INSIDE_WINDOW_CLOCK = "2026-08-05T01:00:00Z"


def round_half_up(value, places: int = 0):
    """Round a rational value half-up, the PRD's single rounding discipline."""
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def bps_of(amount_cents: int, bps: int) -> int:
    """basis points of an amount, rounded half up to whole cents."""
    return int(
        (Decimal(amount_cents) * Decimal(bps) / Decimal(10000)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def premium_bps_for(hammer_price_cents: int) -> int:
    """The flat premium rate the PRD's tier table selects for a hammer price."""
    if hammer_price_cents <= PREMIUM_TIER_1_MAX_CENTS:
        return PREMIUM_TIER_1_BPS
    if hammer_price_cents <= PREMIUM_TIER_2_MAX_CENTS:
        return PREMIUM_TIER_2_BPS
    return PREMIUM_TIER_3_BPS


def pallet_count_for(declared_unit_count: int) -> int:
    return -(-declared_unit_count // UNITS_PER_PALLET)


def estimated_freight_for(declared_unit_count: int) -> int:
    return pallet_count_for(declared_unit_count) * FREIGHT_CENTS_PER_PALLET
