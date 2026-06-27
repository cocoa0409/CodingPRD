"""Calculation rules. PRD §2.7 monetary precision: integer cents, round half up.
Use Decimal everywhere; never float for money."""
from decimal import Decimal, ROUND_HALF_UP

# Constants (SCAFFOLD §1.3)
FULL_CASE_RATE = Decimal("0.15")
MIXED_CASE_RATE = Decimal("0.10")
MIXED_CASE_MIN_UNITS = 12
DEFAULT_SALES_TAX_RATE = Decimal("0.0725")
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 200000
LIMIT_GRACE_ML = 750
LEGAL_FLOOR_AGE = 21


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sales_tax_rate(state_code):
    """PRD §3.6: destination state's rate (or store's state for in-store).
    Only the default 0.0725 rate is in scope."""
    return DEFAULT_SALES_TAX_RATE


def minimum_purchase_age(category, abv_pct):
    """PRD §3.1: always the single legal floor of 21, regardless of category/abv."""
    return LEGAL_FLOOR_AGE


def case_discount(disc_lines):
    """PRD §3.6 case discount, pinned evaluation order.

    disc_lines: list of dicts with keys qty, list_price_cents, case_pack_size
    (GROWLER/KEG lines already excluded by the caller).
    Returns discount_cents (int).
    """
    if not disc_lines:
        return 0

    gross_cents = sum(L["qty"] * L["list_price_cents"] for L in disc_lines)
    total_units = sum(L["qty"] for L in disc_lines)

    full_case_units = 0
    full_case_value = 0
    for L in disc_lines:
        cps = L["case_pack_size"]
        full_portion = L["qty"] - (L["qty"] % cps)
        full_case_units += full_portion
        full_case_value += full_portion * L["list_price_cents"]

    mixed_case_value = gross_cents - full_case_value

    mixed_rate = MIXED_CASE_RATE if total_units >= MIXED_CASE_MIN_UNITS else Decimal("0")

    # Round each component independently THEN sum (pinned).
    full_component = round_half_up(Decimal(full_case_value) * FULL_CASE_RATE)
    mixed_component = round_half_up(Decimal(mixed_case_value) * mixed_rate)
    return full_component + mixed_component


def provisional_order_total(lines, discount_cents, state_code):
    """PRD §3.6 provisional: estimated excise of 0, tax on discounted subtotal."""
    subtotal = sum(L["qty"] * L["unit_price_cents"] for L in lines)
    discounted = subtotal - discount_cents
    rate = sales_tax_rate(state_code)
    est_tax = round_half_up(Decimal(discounted) * rate)
    return discounted + est_tax


def settled_order_total(lines, discount_cents, state_code):
    """PRD §3.6 settled: excise is taxable (added to base BEFORE tax)."""
    subtotal = sum(L["qty"] * L["unit_price_cents"] for L in lines)
    discounted = subtotal - discount_cents
    excise = sum(L["line_excise_cents"] for L in lines)
    taxable_base = discounted + excise
    rate = sales_tax_rate(state_code)
    final_tax = round_half_up(Decimal(taxable_base) * rate)
    return discounted + excise + final_tax


def order_alcohol_volume(lines_with_products):
    """PRD §3.5: sum of qty * parent product's bottle_volume_ml."""
    return sum(qty * bottle_ml for qty, bottle_ml in lines_with_products)


def club_tier_and_multiplier(rolling_spend_cents):
    """PRD §3.8: inclusive thresholds (>=)."""
    if rolling_spend_cents >= GOLD_THRESHOLD_CENTS:
        return "GOLD", Decimal("1.50")
    if rolling_spend_cents >= SILVER_THRESHOLD_CENTS:
        return "SILVER", Decimal("1.25")
    return "BRONZE", Decimal("1.00")


def club_points_for_order(settled_total_cents, multiplier):
    """PRD §3.8: base = floor(settled/100); points = round_half_up(base * mult)."""
    base = settled_total_cents // 100
    return round_half_up(Decimal(base) * multiplier)
