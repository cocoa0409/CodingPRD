"""Calculation rules (scaffold §1.3 / PRD 2.6, 3.5-3.8). Money is integer cents;
non-integer intermediates use Decimal with round-half-up. Points use floor.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

GRADE_MULTIPLIER = {
    "A": Decimal("1.0"),
    "B": Decimal("0.75"),
    "C": Decimal("0.5"),
    "D": Decimal("0.25"),
}
STORE_CREDIT_BONUS = Decimal("0.10")
TAX_RATE = Decimal("0.0725")
TIER_RATE = {
    "STANDARD": Decimal("1.0"),
    "SILVER": Decimal("1.5"),
    "GOLD": Decimal("2.0"),
}
TIER_RANK = {"STANDARD": 1, "SILVER": 2, "GOLD": 3}
MAX_POINTS_PER_SALE = 5000
DAILY_LATE_FEE_CENTS = 500
RENTAL_BUFFER_SECONDS = 24 * 3600
DAY_SECONDS = 24 * 3600


def round_half_up(value):
    """Decimal -> int cents, round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def trade_in_value(base_trade_value_cents, grade, payout_method):
    graded = round_half_up(Decimal(base_trade_value_cents) * GRADE_MULTIPLIER[grade])
    if payout_method == "STORE_CREDIT":
        return round_half_up(Decimal(graded) * (Decimal("1") + STORE_CREDIT_BONUS))
    return graded  # CASH


def ceil_days(seconds):
    """Ceiling of exact hours/24 == ceiling of whole seconds / 86400."""
    if seconds <= 0:
        return 0
    return math.ceil(seconds / DAY_SECONDS)


def planned_days(start_dt, due_dt):
    return ceil_days((due_dt - start_dt).total_seconds())


def late_fee(returned_dt, due_dt):
    # Boundary inclusive at due_at: exactly on time -> 0.
    if returned_dt <= due_dt:
        return 0
    late = ceil_days((returned_dt - due_dt).total_seconds())
    return late * DAILY_LATE_FEE_CENTS


def sale_totals(lines, redeem_store_credit_cents):
    subtotal = sum(line["qty"] * line["unit_price_cents"] for line in lines)
    tax_total = sum(
        round_half_up(Decimal(line["qty"] * line["unit_price_cents"]) * TAX_RATE)
        for line in lines
    )
    total = subtotal + tax_total
    applied_credit = min(redeem_store_credit_cents, total)
    amount_due = total - applied_credit
    return subtotal, tax_total, total, applied_credit, amount_due


def loyalty_points(total_cents, applied_credit_cents, tier):
    cash_portion = total_cents - applied_credit_cents
    raw = math.floor(Decimal(cash_portion) / Decimal(100) * TIER_RATE[tier])
    return min(raw, MAX_POINTS_PER_SALE)
