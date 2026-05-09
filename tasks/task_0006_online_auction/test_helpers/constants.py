"""Domain thresholds — numeric constants from PRD calculations."""

# Bid increment ladder (PRD §3.2). Tier lookup uses STRICT less-than against upper_exclusive_cents.
LADDER = [
    {"upper_exclusive_cents": 10000, "increment_cents": 500},
    {"upper_exclusive_cents": 100000, "increment_cents": 1000},
    {"upper_exclusive_cents": 1000000, "increment_cents": 5000},
    {"upper_exclusive_cents": 10000000, "increment_cents": 10000},
    {"upper_exclusive_cents": None, "increment_cents": 50000},
]


def required_increment(base_cents: int) -> int:
    """Increment cents for given base price."""
    for tier in LADDER:
        upper = tier["upper_exclusive_cents"]
        if upper is None or base_cents < upper:
            return tier["increment_cents"]
    return LADDER[-1]["increment_cents"]


def min_required_bid_cents(current_price_cents: int, starting_bid_cents: int, bid_count: int) -> int:
    """Compute the next bid floor."""
    if bid_count == 0:
        return starting_bid_cents
    return current_price_cents + required_increment(current_price_cents)


# Deposit (PRD §3.2)
DEPOSIT_RATE = 0.10
DEPOSIT_MIN_CENTS = 500
DEPOSIT_MAX_CENTS = 1000000


def deposit_required_cents(reserve_price_cents: int) -> int:
    """deposit_required = clamp(floor(reserve * 0.10), MIN, MAX)."""
    raw = int(reserve_price_cents * 0.10)  # floor for positive ints via int()
    return max(DEPOSIT_MIN_CENTS, min(DEPOSIT_MAX_CENTS, raw))


# Soft-close (PRD §3.2)
SOFT_CLOSE_TRIGGER_SECONDS = 60
SOFT_CLOSE_EXTENSION_SECONDS = 120

# Buyer premium (PRD §3.4)
BP_TIER_1_UPPER_INCLUSIVE_CENTS = 100000
BP_TIER_2_UPPER_INCLUSIVE_CENTS = 1000000
BP_TIER_1_RATE = 0.15
BP_TIER_2_RATE = 0.12
BP_TIER_3_RATE = 0.10
JEWELRY_SURCHARGE_RATE = 0.02
VERIFIED_DISCOUNT_RATE = 0.01
MIN_PREMIUM_CENTS = 100


def buyer_premium_cents(hammer_price_cents: int, category: str, identity_verified: bool) -> int:
    """Average-rate model: single tier rate applies to entire hammer price."""
    if hammer_price_cents <= BP_TIER_1_UPPER_INCLUSIVE_CENTS:
        rate = BP_TIER_1_RATE
    elif hammer_price_cents <= BP_TIER_2_UPPER_INCLUSIVE_CENTS:
        rate = BP_TIER_2_RATE
    else:
        rate = BP_TIER_3_RATE
    if category == "JEWELRY":
        rate += JEWELRY_SURCHARGE_RATE
    if identity_verified:
        rate -= VERIFIED_DISCOUNT_RATE
    raw = int(hammer_price_cents * rate)  # floor
    return max(MIN_PREMIUM_CENTS, raw)


# Seller commission (PRD §3.4)
SC_TIER_1_UPPER_INCLUSIVE_CENTS = 500000
SC_TIER_2_UPPER_INCLUSIVE_CENTS = 5000000
SC_TIER_1_RATE = 0.10
SC_TIER_2_RATE = 0.08
SC_TIER_3_RATE = 0.05


def seller_commission_cents(hammer_price_cents: int) -> int:
    if hammer_price_cents <= SC_TIER_1_UPPER_INCLUSIVE_CENTS:
        rate = SC_TIER_1_RATE
    elif hammer_price_cents <= SC_TIER_2_UPPER_INCLUSIVE_CENTS:
        rate = SC_TIER_2_RATE
    else:
        rate = SC_TIER_3_RATE
    return int(hammer_price_cents * rate)


# Commission reversal (PRD §3.5 / §2.7)
from decimal import Decimal, ROUND_HALF_UP


def commission_reversal_cents(refund_amount_cents: int, buyer_total_cents: int, seller_commission_cents_orig: int) -> int:
    """Decimal: ratio rounded HALF_UP to 4dp, then product rounded HALF_UP to integer cents."""
    ratio = (Decimal(refund_amount_cents) / Decimal(buyer_total_cents)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    product = (Decimal(seller_commission_cents_orig) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(product)


# Default partial refund (PRD §3.4)
PARTIAL_REFUND_RATE_WHEN_REOFFER_FILLED = 0.50


# Risk score (PRD §3.6)
WITHDRAWAL_WEIGHT = 8.0
DISPUTE_LOSS_WEIGHT = 12.0
ACUTE_PENALTY_SHILL = 30.0
ACUTE_PENALTY_TAKEOVER = 20.0
ACUTE_PENALTY_DEFAULT = 20.0
RISK_MAX_SCORE = 100.0
RISK_RESTRICT_THRESHOLD = 70.0
RISK_SUSPEND_THRESHOLD = 90.0


# Shill detection sweep (PRD §3.6)
SHILL_VELOCITY_WINDOW_SECONDS = 30
SHILL_VELOCITY_THRESHOLD = 3  # strictly more than this -> flagged

# Lot duration minimum (PRD §3.1)
LOT_DURATION_MIN_SECONDS = 3600

# Test defaults
TEST_DEFAULTS = {
    "WALLET_LARGE": 10_000_000,        # 100k dollars
    "WALLET_MEDIUM": 1_000_000,        # 10k dollars
    "RESERVE_DEFAULT": 100_000,        # 1k dollars
    "STARTING_DEFAULT": 50_000,        # $500
}
