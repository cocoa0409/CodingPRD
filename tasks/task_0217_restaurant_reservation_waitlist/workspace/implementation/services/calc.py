"""Calculation rules (PRD §2.6, §3.x; scaffold §1.3).

All monetary rounding is half-up to whole cents; reliability is half-up to
one decimal place. Decimal is used to avoid float error.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

NO_SHOW_GRACE_MINUTES = 15
LATE_TIER_HOURS = 2
LATE_TIER_PCT = Decimal("0.50")
NOTIFY_TTL_MINUTES = 10
WAITLIST_EXPIRY_MINUTES = 120
HOLD_EXPIRY_DAYS = 7


def round_half_up_cents(value):
    """Round a Decimal to whole cents (integer), half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round a Decimal to one decimal place, half up, as float."""
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def effective_turn_minutes(table, restaurant):
    """Table override when present, else the restaurant default (§3.3)."""
    if table.get("turn_time_minutes") is not None:
        return table["turn_time_minutes"]
    return restaurant["default_turn_time_minutes"]


def reservation_turn_window(reservation_start, table, restaurant):
    """Compute (turn_window_end, release_at) for a booking (§3.3)."""
    turn = effective_turn_minutes(table, restaurant)
    turn_window_end = reservation_start + timedelta(minutes=turn)
    release_at = turn_window_end + timedelta(minutes=restaurant["cleanup_buffer_minutes"])
    return turn_window_end, release_at


def standard_deposit(restaurant, party_size):
    """Per-seat deposit: exact integer product (§3.4)."""
    return restaurant["per_seat_deposit_cents"] * party_size


def private_dining_deposit(food_minimum_cents, deposit_pct, service_charge_pct):
    """Two components, each rounded half-up to whole cents SEPARATELY, then
    summed — pinned round-then-sum order (§3.4)."""
    food_component = round_half_up_cents(Decimal(food_minimum_cents) * Decimal(str(deposit_pct)))
    service_component = round_half_up_cents(Decimal(food_minimum_cents) * Decimal(str(service_charge_pct)))
    return food_component + service_component


def cancellation_fee(reservation_start, now, party_size, per_seat_cents,
                     late_cutoff_hours, variant, hold_amount_cents=None):
    """Tiered cancellation / no-show fee (§3.5).

    no_show: always 100% of per_seat * party_size.
    late cancel: 0% if early (>= cutoff), 50% if >= 2h out, 100% if < 2h out.
    Always capped at the held amount when a HELD hold exists.
    """
    per_seat = per_seat_cents
    n = party_size
    if variant == "no_show":
        fee = per_seat * n
    else:
        hours_before = (reservation_start - now).total_seconds() / 3600.0
        if hours_before >= late_cutoff_hours:
            fee = 0
        elif hours_before >= LATE_TIER_HOURS:
            fee = round_half_up_cents(LATE_TIER_PCT * Decimal(per_seat) * Decimal(n))
        else:
            fee = per_seat * n
    if hold_amount_cents is not None:
        fee = min(fee, hold_amount_cents)
    return fee


def settled_reliability(lifetime_reservations, lifetime_failures):
    """Settled reliability pct over closed history (§3.2)."""
    denom = lifetime_reservations + lifetime_failures
    if denom == 0:
        return 100.0
    return round_half_up_1dp(Decimal(100) * Decimal(lifetime_reservations) / Decimal(denom))


def provisional_reliability(lifetime_reservations, lifetime_failures, open_confirmed):
    """Provisional reliability: open confirmed bookings projected as future
    successes (added to both numerator and denominator) (§3.2)."""
    numer = lifetime_reservations + open_confirmed
    denom = lifetime_reservations + lifetime_failures + open_confirmed
    if denom == 0:
        return 100.0
    return round_half_up_1dp(Decimal(100) * Decimal(numer) / Decimal(denom))
