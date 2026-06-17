"""Calculation rules (scaffold §1.3 / PRD §3.4, §3.7, §3.9).

All money is integer cents. Basis-point multiplications divide by 10000 and
round half up to whole cents (PRD §2.5). Use Decimal with ROUND_HALF_UP — never
float.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

BPS_DENOM = 10000
BLOCK_MINUTES = 15
CONFIRMED_SURCHARGE_BPS = 1000


def _round_half_up_div(numerator_cents, factor_bps):
    """round_half_up(numerator_cents * factor_bps / 10000) -> int cents."""
    product = Decimal(numerator_cents) * Decimal(factor_bps)
    result = (product / Decimal(BPS_DENOM)).quantize(Decimal("1"),
                                                      rounding=ROUND_HALF_UP)
    return int(result)


def travel_fee(event_zone_id, performer, event_zone, event_miles_from_home):
    """travel_fee calculation.

    Home-zone waiver: if event_zone_id == performer.home_zone_id -> 0 exactly,
    regardless of mileage or surge.
    Else: raw = base_travel_fee_cents + per_mile_fee_cents * miles, then surge
    via round_half_up(raw * surge_multiplier_bps / 10000).
    """
    if event_zone_id == performer["home_zone_id"]:
        return 0
    raw = (event_zone["base_travel_fee_cents"]
           + event_zone["per_mile_fee_cents"] * event_miles_from_home)
    surge_bps = event_zone["surge_multiplier_bps"]
    return _round_half_up_div(raw, surge_bps)


def booking_quote_total(performer, package, equipment_unit_fees, travel):
    """quote_total = set_rate + package_fee + equipment_fee + travel.

    Evaluation order pinned: equipment summed first, then travel added. All
    integer-cent additions are exact.
    """
    set_rate = performer["base_set_rate_cents"]
    package_fee = package["flat_package_fee_cents"]
    equipment_fee = sum(equipment_unit_fees)
    return set_rate + package_fee + equipment_fee + travel


def deposit_required(quote_total_cents, deposit_pct_bps):
    """round_half_up(quote_total_cents * deposit_pct_bps / 10000)."""
    return _round_half_up_div(quote_total_cents, deposit_pct_bps)


def overtime_charge(actual_set_minutes, contracted_set_minutes,
                    overtime_rate_cents_per_15min):
    """extra = max(0, actual - contracted); blocks = ceil(extra / 15);
    overtime = blocks * rate. Boundary: exactly contracted -> 0 blocks;
    contracted+1 -> 1 block."""
    extra = max(0, actual_set_minutes - contracted_set_minutes)
    blocks = math.ceil(extra / BLOCK_MINUTES)
    return blocks * overtime_rate_cents_per_15min


def cancellation_fee(quote_total_cents, event_start_utc, current_clock_utc,
                     booking_status):
    """Tiered cancellation fee with optional CONFIRMED surcharge.

    lead_days = floor((event_start - now) / 86400 seconds).
    >=30 -> 1000 bps; >=14 -> 2500; >=7 -> 5000; else -> 10000.
    CONFIRMED at cancel time adds +1000 bps, capped at 10000.
    fee = round_half_up(quote_total * fee_bps / 10000).
    """
    delta_seconds = (event_start_utc - current_clock_utc).total_seconds()
    lead_days = math.floor(delta_seconds / 86400)
    if lead_days >= 30:
        fee_bps = 1000
    elif lead_days >= 14:
        fee_bps = 2500
    elif lead_days >= 7:
        fee_bps = 5000
    else:
        fee_bps = 10000
    if booking_status == "CONFIRMED":
        fee_bps = min(10000, fee_bps + CONFIRMED_SURCHARGE_BPS)
    return _round_half_up_div(quote_total_cents, fee_bps)
