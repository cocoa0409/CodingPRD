"""Calculation rules (PRD §3.4, §3.5, §3.7, §3.8; SCAFFOLD §1.3).

All money is integer cents. Rounding is half-up (away from zero at the exact half).
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- constants (SCAFFOLD §1.3) ----
SMALL_PARTY_THRESHOLD = 4
SMALL_PARTY_SURCHARGE = Decimal("1.20")

TIER1_CEILING = 20000
TIER2_CEILING = 50000
RATE_LOW_VOLUME = Decimal("0.25")
RATE_MID_VOLUME = Decimal("0.18")
RATE_HIGH_VOLUME = Decimal("0.12")

DEPOSIT_PCT = Decimal("0.30")

FULL_REFUND_DAYS = 14
HALF_REFUND_DAYS = 7

BASE_SCORE = 50
COMPLETE_BONUS = 10
DECLINE_PENALTY = -8
CONFIRMED_PROVISIONAL_BONUS = 10
SCORE_FLOOR = 0
SCORE_CEILING = 100


def round_half_up(value):
    """Round a Decimal to a whole integer, half-up (away from zero at the half)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def labor_total_cents(base_price_per_guest_cents, party_size):
    """PRD §3.4 Labor: surcharge applied to per-guest rate and rounded BEFORE
    multiplying by party_size. party_size < 4 -> *1.20; >= 4 -> base rate."""
    if party_size < SMALL_PARTY_THRESHOLD:
        per_guest = round_half_up(Decimal(base_price_per_guest_cents) * SMALL_PARTY_SURCHARGE)
    else:
        per_guest = base_price_per_guest_cents
    return per_guest * party_size


def select_markup_rate(estimated_ingredient_per_guest_cents, party_size):
    """PRD §3.4 Grocery markup tier: whole-subtotal threshold selection.
    < 20000 -> 0.25; [20000, 50000) -> 0.18; >= 50000 -> 0.12. Returns Decimal."""
    subtotal = estimated_ingredient_per_guest_cents * party_size
    if subtotal < TIER1_CEILING:
        return RATE_LOW_VOLUME
    elif subtotal < TIER2_CEILING:
        return RATE_MID_VOLUME
    else:
        return RATE_HIGH_VOLUME


def estimated_grocery_total_cents(estimated_ingredient_per_guest_cents, party_size, locked_markup_rate):
    """PRD §3.4 Estimated grocery total: subtotal * (1 + rate), round-half-up ONCE."""
    subtotal = estimated_ingredient_per_guest_cents * party_size
    rate = Decimal(str(locked_markup_rate))
    return round_half_up(Decimal(subtotal) * (Decimal(1) + rate))


def actual_grocery_total_cents(line_items, locked_markup_rate):
    """PRD §3.5 Actual grocery total: per-line round-then-sum (NOT sum-then-round).
    Iterate in submitted order; round each line's marked-up cost; sum."""
    rate = Decimal(str(locked_markup_rate))
    total = 0
    for li in line_items:
        line_cost = li["actual_cost_cents"]
        total += round_half_up(Decimal(line_cost) * (Decimal(1) + rate))
    return total


def deposit_due_cents(quote_total_at_confirmation):
    """PRD §3.4 Deposit: quote * 0.30 round-half-up, pinned at confirmation."""
    return round_half_up(Decimal(quote_total_at_confirmation) * DEPOSIT_PCT)


def cancellation_refund_rate(lead_days):
    """PRD §3.8: lead_days >= 14 -> 1.00; >= 7 -> 0.50; else 0.00. Returns Decimal."""
    if lead_days >= FULL_REFUND_DAYS:
        return Decimal("1.00")
    elif lead_days >= HALF_REFUND_DAYS:
        return Decimal("0.50")
    else:
        return Decimal("0.00")


def refund_for_payment(amount_cents, rate):
    """PRD §3.8: refunded_cents = amount * rate, round-half-up per payment."""
    return round_half_up(Decimal(amount_cents) * Decimal(str(rate)))


def clamp_score(value):
    return max(SCORE_FLOOR, min(SCORE_CEILING, value))


def settled_basis(terminal_bookings_ordered):
    """PRD §3.7 settled: chronological accumulation over terminal bookings,
    BEFORE final clamp. Returns the raw accumulated score (int)."""
    score = BASE_SCORE
    for b in terminal_bookings_ordered:
        st = b["lifecycle_status"]
        if st == "COMPLETED":
            score += COMPLETE_BONUS
        elif st == "DECLINED":
            score += DECLINE_PENALTY
        elif st == "CANCELLED":
            score += 0
    return score


def settled_reliability_score(terminal_bookings_ordered):
    """PRD §3.7 settled: clamp(accumulation, 0, 100)."""
    return clamp_score(settled_basis(terminal_bookings_ordered))


def projected_reliability_score(terminal_bookings_ordered, active_confirmed_inprep_count):
    """PRD §3.7 projected: settled accumulation (pre-clamp) + 10 per CONFIRMED/IN_PREP,
    then clamp(0, 100)."""
    basis = settled_basis(terminal_bookings_ordered)
    basis += active_confirmed_inprep_count * CONFIRMED_PROVISIONAL_BONUS
    return clamp_score(basis)
