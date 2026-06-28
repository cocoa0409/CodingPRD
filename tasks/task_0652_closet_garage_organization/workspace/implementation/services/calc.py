"""Calculation rules (PRD 3.3, 3.5, 3.7, 3.8, 3.9 and scaffold 1.3).

All monetary values are integer cents. Rounding is round-half-up at the exact
pinned points described in the PRD. Decimal is used throughout; float is never
used for money.
"""
from decimal import Decimal

from util import round_half_up

# ---- Pricing constants ----
MATERIAL_MULT = {
    "MELAMINE": Decimal("1.00"),
    "LAMINATE": Decimal("1.15"),
    "WOOD": Decimal("1.40"),
    "PREMIUM_WOOD": Decimal("1.80"),
}

PROMO_RATE = {
    "SPRING10": Decimal("0.10"),
    "VIP15": Decimal("0.15"),
}
PROMO_CAP_CENTS = 200000

TAX_RATE = {
    "NORTH": Decimal("0.0725"),
    "SOUTH": Decimal("0.0650"),
    "EAST": Decimal("0.0800"),
    "WEST": Decimal("0.0925"),
}

# ---- Lead time constants ----
MATERIAL_LEAD_ADD = {"MELAMINE": 0, "LAMINATE": 3, "WOOD": 7, "PREMIUM_WOOD": 14}
REGION_LEAD_ADD = {"NORTH": 0, "SOUTH": 2, "EAST": 4, "WEST": 6}

# ---- Deposit constants ----
DEPOSIT_PCT_BY_ROOM = {
    "REACH_IN_CLOSET": Decimal("0.30"),
    "WALK_IN_CLOSET": Decimal("0.35"),
    "GARAGE": Decimal("0.25"),
    "PANTRY": Decimal("0.30"),
    "HOME_OFFICE": Decimal("0.35"),
}

# ---- Financing constants ----
MAX_FINANCE_LTV = Decimal("0.80")
APR_BY_TERM = {
    12: Decimal("0.0000"),
    24: Decimal("0.0599"),
    36: Decimal("0.0899"),
    48: Decimal("0.1199"),
}

WARRANTY_DAYS = 365
COVERED_DEFECTS = {"HARDWARE", "FINISH", "FIT", "STRUCTURAL"}
QUOTE_VALIDITY_DAYS = 30


def volume_rate(total_units: int) -> Decimal:
    if total_units >= 50:
        return Decimal("0.10")
    if total_units >= 20:
        return Decimal("0.05")
    return Decimal("0.00")


def base_lead_days(total_units: int) -> int:
    if total_units >= 50:
        return 35
    if total_units >= 20:
        return 21
    return 14


def config_total_units(line_items) -> int:
    """Sum quantity over all line items EXCEPT ACCESSORY (PRD 3.2)."""
    total = 0
    for li in line_items:
        if li.get("component_type") == "ACCESSORY":
            continue
        total += int(li.get("quantity", 0))
    return total


def quote_estimate_pricing(line_items, material_grade, total_units, region,
                           promo_code):
    """Compute (subtotal_cents, discount_cents, tax_cents, total_cents).

    Pinned order (PRD 3.3):
      1. pre-multiplier subtotal = sum(quantity * unit_price_cents)
      2. priced_subtotal = round_half_up(pre * material_mult)  -> stored subtotal
      3. vol_discount = round_half_up(subtotal * vol_rate)
      4. promo_discount = min(round_half_up((subtotal - vol_discount) * promo_rate), cap)
         discount_cents = vol_discount + promo_discount
      5. taxable = subtotal - discount_cents
         tax_cents = round_half_up(taxable * tax_rate)
      6. total_cents = subtotal - discount_cents + tax_cents
    """
    pre = 0
    for li in line_items:
        pre += int(li.get("quantity", 0)) * int(li.get("unit_price_cents", 0))

    mult = MATERIAL_MULT[material_grade]
    subtotal_cents = round_half_up(Decimal(pre) * mult)

    vrate = volume_rate(total_units)
    vol_discount = round_half_up(Decimal(subtotal_cents) * vrate)

    prate = PROMO_RATE.get(promo_code, Decimal("0")) if promo_code else Decimal("0")
    promo_raw = round_half_up(Decimal(subtotal_cents - vol_discount) * prate)
    promo_discount = min(promo_raw, PROMO_CAP_CENTS)

    discount_cents = vol_discount + promo_discount

    taxable = subtotal_cents - discount_cents
    tax_cents = round_half_up(Decimal(taxable) * TAX_RATE[region])

    total_cents = subtotal_cents - discount_cents + tax_cents
    return subtotal_cents, discount_cents, tax_cents, total_cents


def lead_time_days(total_units: int, material_grade: str, region: str) -> int:
    return (base_lead_days(total_units)
            + MATERIAL_LEAD_ADD[material_grade]
            + REGION_LEAD_ADD[region])


def required_deposit_cents(quote_total_cents: int, room_type: str) -> int:
    pct = DEPOSIT_PCT_BY_ROOM[room_type]
    return round_half_up(Decimal(quote_total_cents) * pct)


def financing_approval(quote_total_cents, requested_amount_cents, term_months):
    """Return (approved_amount_cents, monthly_payment_cents).

    Pinned order: approved first, then monthly payment from it.
    """
    approval_cap = round_half_up(Decimal(quote_total_cents) * MAX_FINANCE_LTV)
    approved = min(requested_amount_cents, approval_cap)

    apr = APR_BY_TERM[term_months]
    if term_months == 12:
        # 0% APR -> simple division, avoids divide-by-zero amortization.
        monthly = round_half_up(Decimal(approved) / Decimal(12))
    else:
        monthly_rate = apr / Decimal(12)
        n = term_months
        denom = Decimal(1) - (Decimal(1) + monthly_rate) ** (-n)
        monthly = round_half_up((Decimal(approved) * monthly_rate) / denom)
    return approved, monthly


def balance_due_cents(accepted_total, deposits_applied, financed):
    """max(accepted_total - deposits - financed, 0). Integer cents."""
    return max(accepted_total - deposits_applied - financed, 0)
