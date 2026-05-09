from decimal import Decimal, ROUND_HALF_UP


# Bid increment ladder per PRD §3.2.
LADDER = [
    (10000, 500),
    (100000, 1000),
    (1000000, 5000),
    (10000000, 10000),
    (None, 50000),
]


def required_increment(base_cents: int) -> int:
    for upper, inc in LADDER:
        if upper is None or base_cents < upper:
            return inc
    return LADDER[-1][1]


def min_required_bid_cents(lot_dict) -> int:
    if lot_dict["bid_count"] == 0:
        return lot_dict["starting_bid_cents"]
    return lot_dict["current_price_cents"] + required_increment(lot_dict["current_price_cents"])


# Deposit calculation per PRD §3.2.
DEPOSIT_RATE = Decimal("0.10")
DEPOSIT_MIN_CENTS = 500
DEPOSIT_MAX_CENTS = 1000000


def deposit_required_cents(reserve_price_cents: int) -> int:
    raw = int((Decimal(reserve_price_cents) * DEPOSIT_RATE).to_integral_value(rounding="ROUND_FLOOR"))
    if raw < DEPOSIT_MIN_CENTS:
        return DEPOSIT_MIN_CENTS
    if raw > DEPOSIT_MAX_CENTS:
        return DEPOSIT_MAX_CENTS
    return raw


# Soft-close per PRD §3.2.
SOFT_CLOSE_TRIGGER_SECONDS = 60
SOFT_CLOSE_EXTENSION_SECONDS = 120


# Buyer premium per PRD §3.4.
BP_TIER_1_UPPER_INCLUSIVE_CENTS = 100000
BP_TIER_2_UPPER_INCLUSIVE_CENTS = 1000000
BP_TIER_1_RATE = Decimal("0.15")
BP_TIER_2_RATE = Decimal("0.12")
BP_TIER_3_RATE = Decimal("0.10")
JEWELRY_SURCHARGE_RATE = Decimal("0.02")
VERIFIED_DISCOUNT_RATE = Decimal("0.01")
MIN_PREMIUM_CENTS = 100


def buyer_premium_cents(hammer_price_cents: int, category: str, identity_verified: bool) -> int:
    if hammer_price_cents <= BP_TIER_1_UPPER_INCLUSIVE_CENTS:
        base = BP_TIER_1_RATE
    elif hammer_price_cents <= BP_TIER_2_UPPER_INCLUSIVE_CENTS:
        base = BP_TIER_2_RATE
    else:
        base = BP_TIER_3_RATE
    rate = base
    if category == "JEWELRY":
        rate += JEWELRY_SURCHARGE_RATE
    if identity_verified:
        rate -= VERIFIED_DISCOUNT_RATE
    raw = (Decimal(hammer_price_cents) * rate).to_integral_value(rounding="ROUND_FLOOR")
    val = int(raw)
    return max(MIN_PREMIUM_CENTS, val)


# Seller commission per PRD §3.4.
SC_TIER_1_UPPER_INCLUSIVE_CENTS = 500000
SC_TIER_2_UPPER_INCLUSIVE_CENTS = 5000000
SC_TIER_1_RATE = Decimal("0.10")
SC_TIER_2_RATE = Decimal("0.08")
SC_TIER_3_RATE = Decimal("0.05")


def seller_commission_cents(hammer_price_cents: int) -> int:
    if hammer_price_cents <= SC_TIER_1_UPPER_INCLUSIVE_CENTS:
        rate = SC_TIER_1_RATE
    elif hammer_price_cents <= SC_TIER_2_UPPER_INCLUSIVE_CENTS:
        rate = SC_TIER_2_RATE
    else:
        rate = SC_TIER_3_RATE
    return int((Decimal(hammer_price_cents) * rate).to_integral_value(rounding="ROUND_FLOOR"))


def commission_reversal_amount_cents(refund_amount_cents: int, buyer_total_cents: int, original_seller_commission_cents: int) -> int:
    if buyer_total_cents == 0:
        return 0
    raw_ratio = Decimal(refund_amount_cents) / Decimal(buyer_total_cents)
    ratio = raw_ratio.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    product = Decimal(original_seller_commission_cents) * ratio
    final = product.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(final)


PARTIAL_REFUND_RATE_WHEN_REOFFER_FILLED = Decimal("0.50")


def default_partial_refund_cents(deposit_amount_cents: int) -> int:
    return int((Decimal(deposit_amount_cents) * PARTIAL_REFUND_RATE_WHEN_REOFFER_FILLED).to_integral_value(rounding="ROUND_FLOOR"))


# Risk score per PRD §3.6.
WITHDRAWAL_WEIGHT = 8.0
DISPUTE_LOSS_WEIGHT = 12.0
ACUTE_PENALTY_SHILL = 30.0
ACUTE_PENALTY_TAKEOVER = 20.0
ACUTE_PENALTY_DEFAULT = 20.0
MAX_SCORE = 100.0
RISK_RESTRICT_THRESHOLD = 70.0
RISK_SUSPEND_THRESHOLD = 90.0


def round_half_up_one_dp(x: float) -> float:
    d = Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


# Time windows.
PAYMENT_DEADLINE_SECONDS = 86400  # 1 day
RUNNER_UP_ACCEPT_WINDOW_SECONDS = 86400  # 1 day
DISPUTE_WINDOW_SECONDS = 604800  # 7 days

# Shill detection.
SHILL_DETECTION_VELOCITY_WINDOW_SECONDS = 30
SHILL_DETECTION_VELOCITY_THRESHOLD = 3
