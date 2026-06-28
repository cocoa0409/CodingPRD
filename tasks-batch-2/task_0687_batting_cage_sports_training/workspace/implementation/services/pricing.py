"""Dual-variant booking pricing and token conversions.

PRD 3.4 booking_quote (forward-looking) — NEVER applies peak.
PRD 3.5 booking_charge (chronological) — applies peak multiplier on lane part.
PRD 2.10 monetary precision: round each component half-up to whole cents FIRST,
sum the rounded components, then apply the tier discount and round half-up ONCE.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from constants import (
    MACHINE_SURCHARGE_CENTS,
    PARTY_BASE_CENTS,
    PARTY_PER_GUEST_CENTS,
    TIER_DISCOUNT_PCT,
    PEAK_START_MIN,
    PEAK_END_MIN,
    PEAK_MULTIPLIER,
)


def _round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _hours(duration_minutes):
    # exact rational hours, kept as Decimal and applied to cents.
    return Decimal(duration_minutes) / Decimal(60)


def _base_lane_rate(lane, facility):
    # lane.hourly_rate_cents override if not null, else facility rate.
    if lane.get("hourly_rate_cents") is not None:
        return Decimal(lane["hourly_rate_cents"])
    return Decimal(facility["hourly_rate_cents"])


def _components(booking, lane, facility, instructor, machine, peak_mult):
    """Compute the four rounded price components (lane/coach/machine/party).

    peak_mult applies only to the lane portion. The quote passes peak_mult=1.0;
    the charge passes the peak-aware multiplier.
    """
    hours = _hours(booking["duration_minutes"])
    base_rate = _base_lane_rate(lane, facility)
    lane_count = Decimal(booking["lane_count"])

    lane_part = _round_half_up(base_rate * hours * lane_count * Decimal(peak_mult))

    if booking["kind"] == "LESSON" and instructor is not None:
        coach_part = _round_half_up(Decimal(instructor["rate_cents_per_hour"]) * hours)
    else:
        coach_part = 0

    if machine is not None:
        machine_part = MACHINE_SURCHARGE_CENTS[machine["model"]]
    else:
        machine_part = 0

    if booking["kind"] == "PARTY":
        party_part = PARTY_BASE_CENTS + booking["party_guests"] * PARTY_PER_GUEST_CENTS
    else:
        party_part = 0

    return lane_part, coach_part, machine_part, party_part


def _apply_discount(gross, tier):
    discount = Decimal(TIER_DISCOUNT_PCT[tier])
    return _round_half_up(Decimal(gross) * (Decimal(1) - discount))


def quote_cost(booking, lane, facility, member, instructor, machine):
    """booking_quote: forward-looking, peak_mult = 1.0 always (PRD 3.4)."""
    lane_part, coach_part, machine_part, party_part = _components(
        booking, lane, facility, instructor, machine, peak_mult=Decimal(1)
    )
    gross = lane_part + coach_part + machine_part + party_part
    return _apply_discount(gross, member["tier"])


def is_peak(start_minute_of_day):
    # PRD 3.5: peak iff start_minute >= PEAK_START_MIN and < PEAK_END_MIN.
    return PEAK_START_MIN <= start_minute_of_day < PEAK_END_MIN


def charge_cost(booking, lane, facility, member, instructor, machine, start_minute_of_day):
    """booking_charge: chronological, lane part * peak_mult (PRD 3.5)."""
    peak_mult = Decimal(PEAK_MULTIPLIER) if is_peak(start_minute_of_day) else Decimal(1)
    lane_part, coach_part, machine_part, party_part = _components(
        booking, lane, facility, instructor, machine, peak_mult=peak_mult
    )
    gross = lane_part + coach_part + machine_part + party_part
    return _apply_discount(gross, member["tier"])


def token_cost(final_cost_cents, token_price_cents):
    """ceil(final_cost_cents / token_price_cents). PRD 3.5: never < 1 when cost > 0."""
    if final_cost_cents <= 0:
        return 0
    return int(
        (Decimal(final_cost_cents) / Decimal(token_price_cents)).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
    )


def refund_tokens_full_or_partial(token_cost_value, full_refund):
    """PRD 3.7 refund waterfall. full_refund True -> full; else forfeit ceil(cost*0.5)."""
    from constants import REFUND_FORFEIT_PCT

    if full_refund:
        return token_cost_value
    forfeit = int(
        (Decimal(token_cost_value) * Decimal(REFUND_FORFEIT_PCT)).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
    )
    return token_cost_value - forfeit


def cents_to_tokens_floor(charged_cents, token_price_cents):
    """PRD 3.8 withdrawal refund: floor(charged_cents / token_price_cents)."""
    if token_price_cents <= 0:
        return 0
    return int(
        (Decimal(charged_cents) / Decimal(token_price_cents)).quantize(
            Decimal("1"), rounding=ROUND_FLOOR
        )
    )
