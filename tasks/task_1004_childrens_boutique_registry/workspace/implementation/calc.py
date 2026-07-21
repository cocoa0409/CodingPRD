"""Pure calculation rules and domain constants."""
from decimal import Decimal, ROUND_HALF_UP

LOW_STOCK_THRESHOLD = 3
COMPLETION_THRESHOLD = 0.80

COMPLETION_DISCOUNT_PCT = Decimal("0.15")
MAX_DISCOUNT_PCT = Decimal("0.25")
LOYALTY_TIER_PCT = {
    "BRONZE": Decimal("0.00"),
    "SILVER": Decimal("0.05"),
    "GOLD": Decimal("0.10"),
    "PLATINUM": Decimal("0.15"),
}
# ordered high -> low
LOYALTY_TIER_THRESHOLDS = [
    ("PLATINUM", 400000),
    ("GOLD", 150000),
    ("SILVER", 50000),
    ("BRONZE", 0),
]
REGISTRY_COMPLETION_BONUS = 250

SEASON_SPLIT = {"IN_SEASON": Decimal("0.60"), "OFF_SEASON": Decimal("0.50")}
CONDITION_BONUS = Decimal("0.05")
PROCESSING_FEE_PCT = Decimal("0.03")
PROCESSING_FEE_CAP_CENTS = 200

TRADE_IN_BASE_PCT = Decimal("0.30")
CONDITION_FACTOR = {
    "LIKE_NEW": Decimal("1.00"),
    "GOOD": Decimal("0.70"),
    "FAIR": Decimal("0.40"),
}
CONDITION_CAP_CENTS = {"LIKE_NEW": 2500, "GOOD": 1500, "FAIR": 800}

PICKUP_BUFFER_MIN = 15


def rhu(value):
    """Round half up to a whole integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def loyalty_tier(lifetime_spend_cents):
    for name, thr in LOYALTY_TIER_THRESHOLDS:
        if lifetime_spend_cents >= thr:
            return name
    return "BRONZE"


def availability_status(on_hand_qty, reserved_qty):
    available = on_hand_qty - reserved_qty
    if available <= 0:
        return "OUT_OF_STOCK"
    if available <= LOW_STOCK_THRESHOLD:
        return "LOW_STOCK"
    return "IN_STOCK"


def completion_pct(fulfilled_value_cents, desired_value_cents):
    if desired_value_cents == 0:
        return 0.0
    q = (Decimal(fulfilled_value_cents) / Decimal(desired_value_cents)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(q)


def loyalty_discount(lines, tier):
    """Per-line rounded loyalty discount, then summed."""
    pct = LOYALTY_TIER_PCT[tier]
    total = 0
    for ln in lines:
        total += rhu(Decimal(ln["line_total_cents"]) * pct)
    return total


def consignor_payout(sale_price_cents, season, condition):
    split = SEASON_SPLIT[season] + (CONDITION_BONUS if condition == "LIKE_NEW" else Decimal("0"))
    gross = rhu(Decimal(sale_price_cents) * split)
    fee = min(rhu(Decimal(sale_price_cents) * PROCESSING_FEE_PCT), PROCESSING_FEE_CAP_CENTS)
    return gross - fee


def trade_in_percent_of_retail(base_price_cents, condition):
    return rhu(Decimal(base_price_cents) * CONDITION_FACTOR[condition] * TRADE_IN_BASE_PCT)


def trade_in_final(base_price_cents, condition):
    return min(
        trade_in_percent_of_retail(base_price_cents, condition),
        CONDITION_CAP_CENTS[condition],
    )
