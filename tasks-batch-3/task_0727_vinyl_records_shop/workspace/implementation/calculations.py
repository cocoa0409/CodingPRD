"""Business calculation rules (§1.3 / PRD §2.5, §3)."""
from decimal import Decimal, ROUND_HALF_UP

GRADE_MULTIPLIER = {
    "M": Decimal("1.10"),
    "NM": Decimal("1.00"),
    "VG_PLUS": Decimal("0.80"),
    "VG": Decimal("0.60"),
    "G": Decimal("0.40"),
    "F": Decimal("0.25"),
    "P": Decimal("0.15"),
}

BUY_MULTIPLIER = {
    "M": Decimal("0.55"),
    "NM": Decimal("0.50"),
    "VG_PLUS": Decimal("0.40"),
    "VG": Decimal("0.30"),
    "G": Decimal("0.20"),
    "F": Decimal("0.10"),
    "P": Decimal("0.05"),
}

CREDIT_BONUS_PCT = Decimal("0.20")

COMMISSION_TIERS = [
    (5000, Decimal("0.30")),
    (20000, Decimal("0.20")),
    (99999999, Decimal("0.10")),
]

LOYALTY_DISCOUNT_PCT = {
    "STANDARD": Decimal("0.00"),
    "SILVER": Decimal("0.05"),
    "GOLD": Decimal("0.10"),
}
FREE_SHIP_THRESHOLD_CENTS = 5000
FLAT_SHIP_CENTS = 599

POINTS_MULTIPLIER = {
    "STANDARD": Decimal("1.0"),
    "SILVER": Decimal("1.0"),
    "GOLD": Decimal("1.5"),
}
SILVER_MIN = 100
GOLD_MIN = 500

GRADES = {"M", "NM", "VG_PLUS", "VG", "G", "F", "P"}


def round_half_up(value):
    """Round a Decimal to a whole integer (cents), half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def item_list_price(base_price_cents, condition_grade, is_used, consignment_list_price=None):
    """Compute InventoryItem.list_price_cents (item_list_price calc)."""
    if consignment_list_price is not None:
        return consignment_list_price
    mult = GRADE_MULTIPLIER[condition_grade]
    raw = Decimal(base_price_cents) * mult
    price = round_half_up(raw)
    if not is_used:
        price = max(price, base_price_cents)
    return price


def trade_in_value(lines_grades_values, payout_method, final):
    """trade_in_credit_valuation.

    lines_grades_values: list of (grade, base_value_cents).
    Round each line first, then sum. For final CREDIT, apply bonus after summation.
    """
    total = 0
    for grade, base_value in lines_grades_values:
        total += round_half_up(Decimal(base_value) * BUY_MULTIPLIER[grade])
    if final and payout_method == "CREDIT":
        total = round_half_up(Decimal(total) * (Decimal("1") + CREDIT_BONUS_PCT))
    return total


def consignment_payout(price_cents):
    """consignment_payout: tiered marginal commission, per-tier rounding pinned."""
    commission = 0
    prev = 0
    for bound, rate in COMMISSION_TIERS:
        slice_amt = max(0, min(price_cents, bound) - prev)
        commission += round_half_up(Decimal(slice_amt) * rate)
        prev = bound
    return price_cents - commission


def order_totals(lines, channel, loyalty_tier):
    """order_total calc. lines: list of dicts with unit_price_cents, qty, is_used.

    Returns (subtotal, discount, shipping, total).
    """
    subtotal = sum(l["unit_price_cents"] * l["qty"] for l in lines)
    new_subtotal = sum(
        l["unit_price_cents"] * l["qty"] for l in lines if not l["is_used"]
    )
    discount = round_half_up(Decimal(new_subtotal) * LOYALTY_DISCOUNT_PCT[loyalty_tier])
    if channel == "IN_STORE":
        shipping = 0
    else:
        shipping = 0 if subtotal >= FREE_SHIP_THRESHOLD_CENTS else FLAT_SHIP_CENTS
    total = subtotal - discount + shipping
    return subtotal, discount, shipping, total


def loyalty_points_earned(total_cents, loyalty_tier):
    base_points = total_cents // 100
    return int((Decimal(base_points) * POINTS_MULTIPLIER[loyalty_tier]).to_integral_value(rounding="ROUND_FLOOR"))


def loyalty_tier(loyalty_points):
    if loyalty_points >= GOLD_MIN:
        return "GOLD"
    if loyalty_points >= SILVER_MIN:
        return "SILVER"
    return "STANDARD"
