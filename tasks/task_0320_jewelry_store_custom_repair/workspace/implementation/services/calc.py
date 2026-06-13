"""Calculation rules (PRD §2.6, §3, SCAFFOLD §1.3). All money is integer cents.

round_half_up: a value whose fractional part is exactly one-half rounds away
from zero to the next whole cent (PRD §2.6).
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- custom_order_totals constants ----
PROVISIONAL_MARKUP = Decimal("0.20")
DEPOSIT_PCT = Decimal("0.30")

# ---- layaway_schedule constants ----
DOWN_PAYMENT_PCT = Decimal("0.20")
RESTOCK_PCT = Decimal("0.15")
MAX_RESTOCK_CENTS = 50000

# ---- trade_in_credit constants ----
PURITY_FACTOR = {"K14": Decimal("0.585"), "K18": Decimal("0.750"), "K24": Decimal("1.000")}
CONDITION_FACTOR = {"EXCELLENT": Decimal("0.90"), "GOOD": Decimal("0.75"), "FAIR": Decimal("0.55")}
MIN_BUYBACK_CENTS = 2500
MAX_BUYBACK_CENTS = 5000000

# ---- repair_total constants ----
RUSH_TIER1_MAX = 10000
RUSH_TIER2_MAX = 50000
RUSH_PCT_LOW = Decimal("0.10")
RUSH_PCT_MID = Decimal("0.20")
RUSH_PCT_HIGH = Decimal("0.30")

# ---- special_order ----
SPECIAL_ORDER_DEPOSIT_PCT = Decimal("0.30")

# ---- scheduling ----
APPRAISAL_BUFFER_MINUTES = 30

MAX_REVISIONS = 3


def round_half_up(value):
    """Round a Decimal to a whole integer using ROUND_HALF_UP (away from zero)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- custom order
def provisional_total_cents(estimated_materials_cents, design_fee_cents):
    materials = round_half_up(Decimal(estimated_materials_cents) * (Decimal("1") + PROVISIONAL_MARKUP))
    return materials + design_fee_cents


def deposit_required_cents(provisional_total):
    return round_half_up(DEPOSIT_PCT * Decimal(provisional_total))


def final_total_cents(line_items, design_fee_cents):
    """Round each line independently, THEN sum, then add design fee (PRD §2.6, §3.3)."""
    subtotal = 0
    for line in line_items:
        qty = Decimal(str(line["qty"]))
        unit = Decimal(str(line["unit_price_cents"]))
        markup = Decimal(str(line["markup_pct"]))
        line_total = round_half_up(qty * unit * (Decimal("1") + markup))
        subtotal += line_total
    return subtotal + design_fee_cents


# ---------------------------------------------------------------- layaway
def down_payment_cents(item_price_cents):
    return round_half_up(DOWN_PAYMENT_PCT * Decimal(item_price_cents))


def installment_amount_cents(item_price_cents, down_payment, installment_count):
    """floor((item_price - down_payment) / count). Final installment absorbs remainder."""
    remaining = item_price_cents - down_payment
    return remaining // installment_count


def restocking_fee_cents(item_price_cents):
    return min(MAX_RESTOCK_CENTS, round_half_up(RESTOCK_PCT * Decimal(item_price_cents)))


def settlement_refund_cents(paid_to_date, restock_fee):
    return max(0, paid_to_date - restock_fee)


# ---------------------------------------------------------------- trade-in
def metal_value_cents(metal_weight_grams, spot_price_cents_per_gram, metal_karat):
    raw = Decimal(str(metal_weight_grams)) * Decimal(spot_price_cents_per_gram) * PURITY_FACTOR[metal_karat]
    return round_half_up(raw)


def buyback_credit_cents(metal_value, gemstone_value_cents, condition):
    raw_credit = round_half_up((Decimal(metal_value) + Decimal(gemstone_value_cents)) * CONDITION_FACTOR[condition])
    return min(MAX_BUYBACK_CENTS, max(MIN_BUYBACK_CENTS, raw_credit))


# ---------------------------------------------------------------- repair total
def repair_total(parts_cents, labor_cents, rush, is_warranty):
    """Returns (rush_surcharge_cents, total_cents). Pinned eval order (PRD §3.4)."""
    subtotal = parts_cents + labor_cents
    if is_warranty:
        return 0, 0
    if not rush:
        return 0, subtotal
    if subtotal < RUSH_TIER1_MAX:
        pct = RUSH_PCT_LOW
    elif subtotal <= RUSH_TIER2_MAX:
        pct = RUSH_PCT_MID
    else:
        pct = RUSH_PCT_HIGH
    surcharge = round_half_up(Decimal(subtotal) * pct)
    return surcharge, subtotal + surcharge


# ---------------------------------------------------------------- special order
def special_order_deposit_required_cents(quoted_price_cents):
    return round_half_up(SPECIAL_ORDER_DEPOSIT_PCT * Decimal(quoted_price_cents))


# ---------------------------------------------------------------- appraisal
def replacement_value_cents(market_value_cents, replacement_factor):
    return round_half_up(Decimal(market_value_cents) * Decimal(str(replacement_factor)))
