"""Pricing & utility-settlement calculations (PRD §3.5, §3.6, §3.8).

All arithmetic is in integer cents. The per-night raw amount is rounded
half-up to a whole cent BEFORE summation across nights — see PRD §2.8.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# ---- Calculation constants (SCAFFOLD §1.3) ---------------------------------

LIVEABOARD_SURCHARGE_CENTS = 1500           # $15.00/day
SEASON_PEAK_MULTIPLIER = Decimal("1.50")    # Jun-Aug
SEASON_SHOULDER_MULTIPLIER = Decimal("1.20")  # Apr-May, Sep-Oct
SEASON_OFF_MULTIPLIER = Decimal("1.00")     # all other months
SEASON_PEAK_MONTHS = {6, 7, 8}
SEASON_SHOULDER_MONTHS = {4, 5, 9, 10}

KWH_RATE_CENTS = 18                         # $0.18/kWh
WATER_RATE_CENTS_PER_GAL = 4                # $0.04/gal
SEWAGE_FLAT_CENTS = 2500                    # $25.00 flat per liveaboard settlement (if water>0)

TOW_FLAT_FEE_CENTS = 25000                  # $250.00 per BASIC tow once allotment exhausted


# ---- Helpers ----------------------------------------------------------------


def season_multiplier_for_month(month: int) -> Decimal:
    if month in SEASON_PEAK_MONTHS:
        return SEASON_PEAK_MULTIPLIER
    if month in SEASON_SHOULDER_MONTHS:
        return SEASON_SHOULDER_MULTIPLIER
    return SEASON_OFF_MULTIPLIER


def _round_half_up_to_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _per_night_cents(
    base_daily_rate_cents: int,
    loa_feet,
    flat_daily_charge_cents: int,
    liveaboard: bool,
    multiplier: Decimal,
) -> int:
    """One night's price, rounded half-up to integer cents."""
    raw = (
        Decimal(base_daily_rate_cents) * Decimal(str(loa_feet)) * multiplier
        + Decimal(flat_daily_charge_cents)
        + (Decimal(LIVEABOARD_SURCHARGE_CENTS) if liveaboard else Decimal(0))
    )
    return _round_half_up_to_int(raw)


def whole_day_nights(check_in: datetime, check_out: datetime) -> int:
    """Half-open [check_in, check_out) in whole days."""
    delta = check_out - check_in
    return delta.days


def forward_looking_total(
    *,
    base_daily_rate_cents: int,
    loa_feet,
    flat_daily_charge_cents: int,
    liveaboard: bool,
    check_in_date: datetime,
    check_out_date: datetime,
) -> int:
    """Forward-looking estimate frozen at the check-in date's season multiplier (§3.5)."""
    nights = whole_day_nights(check_in_date, check_out_date)
    multiplier = season_multiplier_for_month(check_in_date.month)
    per_night = _per_night_cents(
        base_daily_rate_cents,
        loa_feet,
        flat_daily_charge_cents,
        liveaboard,
        multiplier,
    )
    return per_night * nights


def chronological_total(
    *,
    base_daily_rate_cents: int,
    loa_feet,
    flat_daily_charge_cents: int,
    liveaboard: bool,
    check_in_date: datetime,
    check_out_date: datetime,
) -> int:
    """Chronological total — re-evaluates season per night (§3.5)."""
    total = 0
    night = check_in_date
    # Ensure UTC awareness for date iteration safety
    if night.tzinfo is None:
        night = night.replace(tzinfo=timezone.utc)
    end = check_out_date if check_out_date.tzinfo else check_out_date.replace(tzinfo=timezone.utc)
    while night < end:
        multiplier = season_multiplier_for_month(night.month)
        per_night = _per_night_cents(
            base_daily_rate_cents,
            loa_feet,
            flat_daily_charge_cents,
            liveaboard,
            multiplier,
        )
        total += per_night
        night = night + timedelta(days=1)
    return total


def settlement_for_readings(
    *,
    readings: list,
    liveaboard: bool,
) -> dict:
    """Aggregate utility readings into a settlement payload (§3.6)."""
    kwh_total = sum(int(r.get("kwh_delta", 0)) for r in readings)
    water_total = sum(int(r.get("water_gallons_delta", 0)) for r in readings)
    kwh_charge = kwh_total * KWH_RATE_CENTS
    water_charge = water_total * WATER_RATE_CENTS_PER_GAL
    if liveaboard and water_total > 0:
        sewage_charge = SEWAGE_FLAT_CENTS
    else:
        sewage_charge = 0
    return {
        "kwh_total": kwh_total,
        "water_gallons_total": water_total,
        "sewage_charge_cents": sewage_charge,
        "total_cents": kwh_charge + water_charge + sewage_charge,
    }


def tow_event_charge(*, tier: str, tows_remaining: int) -> tuple[int, int]:
    """Return (charge_cents, new_tows_remaining) per §3.8."""
    if tier == "PREMIUM":
        return 0, tows_remaining  # sentinel -1 preserved
    if tier == "BASIC" and tows_remaining > 0:
        return 0, tows_remaining - 1
    # BASIC with zero remaining
    return TOW_FLAT_FEE_CENTS, tows_remaining
