"""Calculation rules (PRD section 3 / scaffold section 1.3).

All money is whole integer cents. Fractional cents resolve with round-half-up.
Quantities arriving as JSON floats are converted via Decimal(str(x)) so that a
value like 1.333 keeps its exact decimal form rather than its IEEE-754 noise.
"""
from decimal import Decimal, ROUND_HALF_UP

# ── Booking fee (PRD 3.3) ──
RATE_BY_CLASS = {"PREP_TABLE": 1200, "CONVECTION_OVEN": 3000, "BLAST_CHILLER": 2500}
PEAK_MULT = Decimal("1.5")
OFFPEAK_MULT = Decimal("1.0")
CLEANING_SURCHARGE = 800

# ── Production fee (PRD 3.8) ──
FACILITY_FEE_PER_UNIT = 35
VOLUME_THRESHOLD = 100
VOLUME_REBATE = 500

# ── Storage fee (PRD 3.10) ──
SLOT_RATE_BY_CLASS = {"DRY": 400, "COLD": 700, "FROZEN": 900}
PREMIUM_STORAGE_DISCOUNT = Decimal("0.05")

# ── Actual food cost (PRD 3.7) ──
SPOILAGE_PCT = Decimal("0.05")

# ── Invoice total (PRD 3.13) ──
PLATFORM_FEE_PCT = Decimal("0.03")
DISCOUNT_TIER_HIGH = 50000
DISCOUNT_TIER_MID = 20000
DISCOUNT_PCT_HIGH = Decimal("0.10")
DISCOUNT_PCT_MID = Decimal("0.05")

# ── Temperature excursion (PRD 3.11) ──
EXCURSION_LIMIT_MINUTES = 120


def round_half_up(value):
    """Round a Decimal (or number) to the nearest whole cent, halves up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _dec(x):
    """Exact Decimal from a possibly-float quantity."""
    return Decimal(str(x))


def booking_fee(station_class, duration_minutes, is_peak, turnover_applied):
    """PRD 3.3: round the scaled base once, then add the flat cleaning surcharge."""
    rate = RATE_BY_CLASS[station_class]
    mult = PEAK_MULT if is_peak else OFFPEAK_MULT
    base = Decimal(rate) * (_dec(duration_minutes) / Decimal(60)) * mult
    base_cents = round_half_up(base)
    fee = base_cents + (CLEANING_SURCHARGE if turnover_applied else 0)
    return fee


def estimated_food_cost(components, ingredient_cost_by_id, scale):
    """PRD 3.5: ROUND-PER-LINE-THEN-SUM.

    components: list of {ingredient_id, planned_qty}
    ingredient_cost_by_id: {ingredient_id: unit_cost_cents}
    scale: Decimal-compatible scale factor (1.0 at publish).
    """
    scale = _dec(scale)
    total = 0
    for comp in components:
        line_qty = _dec(comp["planned_qty"]) * scale
        unit_cost = ingredient_cost_by_id[comp["ingredient_id"]]
        line_cents = round_half_up(line_qty * Decimal(unit_cost))
        total += line_cents
    return total


def actual_food_cost(actual_lines, ingredient_cost_by_id):
    """PRD 3.7: per-line round, sum to base, then add 5% spoilage (round-half-up).

    actual_lines: list of {ingredient_id, actual_qty}
    Returns (actual_food_cost_cents, base_cents, spoilage_cents).
    """
    base = 0
    for line in actual_lines:
        unit_cost = ingredient_cost_by_id[line["ingredient_id"]]
        line_cents = round_half_up(_dec(line["actual_qty"]) * Decimal(unit_cost))
        base += line_cents
    spoilage = round_half_up(Decimal(base) * SPOILAGE_PCT)
    return base + spoilage, base, spoilage


def production_fee(actual_yield_units):
    """PRD 3.8: base = yield * 35; flat 500 rebate at yield >= 100; floor at 0."""
    base_fee = actual_yield_units * FACILITY_FEE_PER_UNIT
    rebate = VOLUME_REBATE if actual_yield_units >= VOLUME_THRESHOLD else 0
    return max(0, base_fee - rebate)


def storage_fee(temp_class, requested_slots, plan_tier):
    """PRD 3.10: gross = slots * rate; PREMIUM gets 5% discount (round-half-up)."""
    rate = SLOT_RATE_BY_CLASS[temp_class]
    gross = requested_slots * rate
    if plan_tier == "PREMIUM":
        discount = round_half_up(Decimal(gross) * PREMIUM_STORAGE_DISCOUNT)
    else:
        discount = 0
    return gross - discount


def invoice_totals(booking_subtotal, storage_subtotal, production_subtotal):
    """PRD 3.13: subtotal -> discount(tier on subtotal) -> platform fee(subtotal) -> total."""
    subtotal = booking_subtotal + storage_subtotal + production_subtotal
    if subtotal >= DISCOUNT_TIER_HIGH:
        disc_pct = DISCOUNT_PCT_HIGH
    elif subtotal >= DISCOUNT_TIER_MID:
        disc_pct = DISCOUNT_PCT_MID
    else:
        disc_pct = Decimal("0")
    loyalty_discount = round_half_up(Decimal(subtotal) * disc_pct)
    platform_fee = round_half_up(Decimal(subtotal) * PLATFORM_FEE_PCT)
    total = subtotal - loyalty_discount + platform_fee
    return {
        "subtotal_cents": subtotal,
        "loyalty_discount_cents": loyalty_discount,
        "platform_fee_cents": platform_fee,
        "total_cents": total,
    }
