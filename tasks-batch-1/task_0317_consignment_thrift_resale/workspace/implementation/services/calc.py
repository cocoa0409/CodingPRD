"""Calculation rules (scaffold §1.3 / PRD §2.6, §3.5-3.9).

All money is integer cents. round_half_up and floor are used exactly where the
PRD specifies. Decimal is used so half-up rounding is exact.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# Store configuration constants (frozen on records at write time).
PROCESSING_FEE_CENTS = 150
BONUS_TIER1_MIN_CENTS = 2000
BONUS_TIER1_PCT = Decimal("0.10")
BONUS_TIER2_MIN_CENTS = 10000
BONUS_TIER2_PCT = Decimal("0.20")
DONATION_VALUATION_PCT = Decimal("0.25")
SECONDS_PER_DAY = 86400


def round_half_up(value):
    """Round a Decimal/number half-up to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value):
    """Floor a Decimal/number toward zero to an integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def markdown_floor_cents(list_price_cents, base_floor_pct):
    """floor(list_price_cents * base_floor_pct)."""
    return floor_int(Decimal(list_price_cents) * Decimal(str(base_floor_pct)))


def age_days(floor_dt, now_dt):
    """Whole days since floor_date: floor((NOW - floor_date)/86400s)."""
    delta = (now_dt - floor_dt).total_seconds()
    if delta < 0:
        delta = 0
    return int(delta // SECONDS_PER_DAY)


def select_tier(tiers, age):
    """Step function: tier with greatest min_age_days <= age."""
    applicable = None
    for t in tiers:
        if t["min_age_days"] <= age:
            if applicable is None or t["min_age_days"] > applicable["min_age_days"]:
                applicable = t
    return applicable


def markdown_price(list_price_cents, floor_dt, now_dt, schedule):
    """current_price_cents from list price, age on floor, and the schedule."""
    age = age_days(floor_dt, now_dt)
    tier = select_tier(schedule["tiers"], age)
    discount_pct = tier["discount_pct"] if tier is not None else 0
    raw_price = round_half_up(
        Decimal(list_price_cents) * (Decimal(1) - Decimal(str(discount_pct)))
    )
    floor_price = markdown_floor_cents(list_price_cents, schedule["base_floor_pct"])
    return max(raw_price, floor_price)


def split_base(sold_price_cents, processing_fee_cents, split_basis):
    if split_basis == "GROSS":
        return sold_price_cents
    # NET
    return max(0, sold_price_cents - processing_fee_cents)


def consignor_proceeds(split_base_cents, split_pct):
    return round_half_up(Decimal(split_base_cents) * Decimal(str(split_pct)))


def store_credit_payout(proceeds_cents):
    """Base proceeds upgraded by a tiered bonus -> issued amount."""
    base = proceeds_cents
    if base >= BONUS_TIER2_MIN_CENTS:
        bonus = round_half_up(Decimal(base) * BONUS_TIER2_PCT)
    elif base >= BONUS_TIER1_MIN_CENTS:
        bonus = round_half_up(Decimal(base) * BONUS_TIER1_PCT)
    else:
        bonus = 0
    return base + bonus


def donation_valuation(list_price_cents, disposition):
    if disposition == "DONATED":
        return floor_int(Decimal(list_price_cents) * DONATION_VALUATION_PCT)
    return 0
