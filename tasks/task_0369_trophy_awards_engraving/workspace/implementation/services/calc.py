"""Calculation rules (scaffold §1.3, PRD §3.4, §3.5, §3.8).

All money is integer cents. Multiplications by a fractional rate are FLOORED
(toward zero / round_down) except the deposit which is CEILed. On-time-rate is
the only non-cents figure, rounded half-up to 2 decimals.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP


# ---- volume discount tiers ----
TIER1_MIN, TIER2_MIN, TIER3_MIN = 25, 50, 100
TIER1_PCT, TIER2_PCT, TIER3_PCT = Decimal("0.05"), Decimal("0.10"), Decimal("0.15")

DEPOSIT_PCT = Decimal("0.50")

# ship fee constants
SHIP_BASE = 1200
SHIP_PER_KG = 300
SHIP_PER_KG_HEAVY = 500


def floor_mul(cents, rate):
    """Floor toward zero of cents * rate where rate is a fraction. cents and the
    product are non-negative in this domain, so floor == truncate."""
    return int(math.floor(Decimal(cents) * Decimal(str(rate))))


def char_count(text):
    return len(text or "")


def line_subtotal(line, product):
    """quantity*(base + char_count*per_char) + (logo_fee once if include_logo)."""
    cc = char_count(line.get("engraving_text", ""))
    per_unit = product["base_price_cents"] + cc * product["engraving_price_per_char_cents"]
    logo_fee = product["logo_setup_fee_cents"] if line.get("include_logo") else 0
    subtotal = line["quantity"] * per_unit + logo_fee
    return cc, subtotal


def volume_discount(line, product):
    """Returns (volume_tier, volume_discount_cents). Discount applies to engraved
    goods only (subtotal minus the one-time logo fee), floored."""
    q = line["quantity"]
    if q >= TIER3_MIN:
        tier, pct = "TIER3", TIER3_PCT
    elif q >= TIER2_MIN:
        tier, pct = "TIER2", TIER2_PCT
    elif q >= TIER1_MIN:
        tier, pct = "TIER1", TIER1_PCT
    else:
        tier, pct = "NONE", Decimal("0")
    logo_fee = product["logo_setup_fee_cents"] if line.get("include_logo") else 0
    goods = line["line_subtotal_cents"] - logo_fee
    discount = int(math.floor(Decimal(goods) * pct)) if pct > 0 else 0
    return tier, discount


def business_days_to_due(now_dt, due_dt):
    """Number of business days from 'now' date to due date, exclusive of today,
    weekends excluded. Counts weekdays strictly after today up to and including
    the due date."""
    start = now_dt.date()
    end = due_dt.date()
    if end <= start:
        return 0
    count = 0
    d = start + timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:  # Mon..Fri
            count += 1
        d += timedelta(days=1)
    return count


def resolve_rush_tier(bd, policy, product_max_standard_lead):
    """Returns (rush_tier, surcharge_pct). Caller must already have checked
    bd >= rush_min_business_days (ERR_DUE_DATE_INFEASIBLE)."""
    if bd < 3:
        return "RUSH", policy["rush_surcharge_pct"]
    elif bd < product_max_standard_lead:
        return "EXPEDITED", policy["expedited_surcharge_pct"]
    else:
        return "STANDARD", policy["standard_surcharge_pct"]


def order_pricing(subtotal_cents, surcharge_pct, promo, apply_promo):
    """Returns (pre_promo_cents, total_cents). Order pinned: subtotal -> rush -> promo.

    subtotal_cents: exact integer sum over lines of (line_subtotal - volume_discount).
    promo applied only when apply_promo and subtotal >= promo.min_subtotal_cents.
    """
    rush_amount = floor_mul(subtotal_cents, surcharge_pct)
    pre_promo = subtotal_cents + rush_amount
    promo_cents = 0
    if apply_promo and promo is not None:
        if subtotal_cents >= promo.get("min_subtotal_cents", 0):
            if promo["kind"] == "PERCENT":
                promo_cents = floor_mul(subtotal_cents, promo["percent_off"])
            else:  # FLAT
                promo_cents = min(promo["flat_off_cents"], pre_promo)
    total = max(0, pre_promo - promo_cents)
    return pre_promo, total


def deposit_due(invoice_total_cents, rush_tier):
    if rush_tier == "RUSH":
        return invoice_total_cents
    return int(math.ceil(Decimal(invoice_total_cents) * DEPOSIT_PCT))


def ship_fee(weight_grams):
    """Tiered ship fee by weight. Caller validates weight > 0 for SHIP."""
    w = weight_grams
    if w <= 1000:
        return SHIP_BASE
    elif w <= 5000:
        extra_kg = (w - 1000) // 1000
        return SHIP_BASE + extra_kg * SHIP_PER_KG
    else:
        heavy_kg = (w - 5000) // 1000
        return SHIP_BASE + 4 * SHIP_PER_KG + heavy_kg * SHIP_PER_KG_HEAVY


def on_time_rate(fulfilled_orders):
    """round_half_up(on_time/total*100, 2); None if no fulfilled orders."""
    total = len(fulfilled_orders)
    if total == 0:
        return None
    on_time = sum(1 for o in fulfilled_orders if o.get("due_date_met") is True)
    val = Decimal(on_time) / Decimal(total) * Decimal(100)
    rounded = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)
