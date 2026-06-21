"""Pure calculation rules from PRD section 3 / SCAFFOLD section 1.3.

All money is integer cents. Rounding rules are part of the contract.
"""
from helpers import round_half_up, floor_div

# --- seat_subtotal_cents constants ---
SPLIT_SURCHARGE_CENTS = 1500
GROUP_THRESHOLD = 4
GROUP_DISCOUNT_PCT = 10

# --- deposit_due_cents constants ---
DEPOSIT_PCT = 25
MIN_DEPOSIT_CENTS = 2000

# --- addon_line_total_cents constants ---
ADDON_RATE_CARD = {
    "BAIT": 800,
    "ROD_RENTAL": 2500,
    "FISH_CLEANING": 1200,
    "COOLER_ICE": 600,
}
BULK_QTY = 10
BULK_PCT = 15

# --- cancellation_refund_cents constants ---
FULL_REFUND_HOURS = 72
PARTIAL_REFUND_HOURS = 24
PARTIAL_PCT = 50

# --- gratuity_cents constants ---
AUTO_GRAT_PARTY = 6
AUTO_GRAT_PCT = 20

# --- reschedule_fee_cents constants ---
FIRST_RESCHEDULE_FEE_CENTS = 1000
SECOND_RESCHEDULE_FEE_CENTS = 2500
REPEAT_RESCHEDULE_PCT = 15


def seat_subtotal_cents(base_seat_price_cents, split_charter, party_size):
    """Fixed evaluation order: resolve per-seat -> floor group discount on
    per-seat BEFORE multiply -> multiply by party_size (no further rounding)."""
    eff_seat = base_seat_price_cents
    if split_charter:
        eff_seat = eff_seat + SPLIT_SURCHARGE_CENTS
    if party_size >= GROUP_THRESHOLD:
        # floor(eff_seat * (100 - GROUP_DISCOUNT_PCT) / 100) on the per-seat figure
        eff_seat = floor_div(eff_seat * (100 - GROUP_DISCOUNT_PCT), 100)
    return eff_seat * party_size


def deposit_due_cents(seat_subtotal):
    """25% of subtotal, round half up, clamped to [MIN_DEPOSIT, subtotal]."""
    rounded = round_half_up(seat_subtotal * DEPOSIT_PCT, 100)
    return max(MIN_DEPOSIT_CENTS, min(rounded, seat_subtotal))


def addon_line_total_cents(addon_kind, quantity):
    unit_price = ADDON_RATE_CARD[addon_kind]
    gross = unit_price * quantity
    if quantity >= BULK_QTY:
        discount = floor_div(gross * BULK_PCT, 100)
        return unit_price, gross - discount
    return unit_price, gross


def cancellation_refund_cents(weather_waiver, deposit_paid, lead_hours):
    """Refund of deposit_paid. Boundaries inclusive on lower side (>=)."""
    if weather_waiver:
        return deposit_paid
    if lead_hours >= FULL_REFUND_HOURS:
        return deposit_paid
    if lead_hours >= PARTIAL_REFUND_HOURS:
        return round_half_up(deposit_paid * PARTIAL_PCT, 100)
    return 0


def gratuity_cents(seat_subtotal, addon_base, party_size, mode, value):
    """Tip base = seat_subtotal + non-voided addon line totals.
    Compute customer tip, then apply auto-grat floor (max) AFTER."""
    tip_base = seat_subtotal + addon_base
    if mode == "PERCENT":
        tip = round_half_up(tip_base * value, 100)
    else:  # FLAT
        tip = value
    if party_size >= AUTO_GRAT_PARTY:
        floor_tip = round_half_up(tip_base * AUTO_GRAT_PCT, 100)
        tip = max(tip, floor_tip)
    return tip


def reschedule_fee_cents(weather_reschedule_count_before, seat_subtotal):
    """Tier keyed on the PRE-increment count. GOLD waiver handled by caller."""
    n = weather_reschedule_count_before
    if n == 0:
        return FIRST_RESCHEDULE_FEE_CENTS
    if n == 1:
        return SECOND_RESCHEDULE_FEE_CENTS
    return round_half_up(seat_subtotal * REPEAT_RESCHEDULE_PCT, 100)
