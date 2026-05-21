"""Fare calculations: quoted (forward-looking) and final (chronological).

PRD §3.3, §3.4 / scaffold §1.3.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from ..store import store
from ..util import round_half_up_decimal, round_half_up_int

BASE_FARE_CENTS = 250
PER_KM_CENTS = 120
MULTIPLIER_CAP = Decimal("3.00")
PLATFORM_FEE_RATE = Decimal("0.20")

DAY_OF_WEEK_MAP = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def base_fare_cents_for(distance_km) -> int:
    """BASE_FARE_CENTS + round_half_up(distance_km * PER_KM_CENTS)."""
    d = Decimal(str(distance_km))
    additive = round_half_up_int(d * Decimal(PER_KM_CENTS))
    return BASE_FARE_CENTS + additive


def find_active_rush_hour_bonus(grid: Dict[str, Any]) -> Decimal:
    """Return the additive_bonus of the first matching active RushHourWindow at now() for this grid.

    Only fires if grid['rush_hour_eligible'] is True. Half-open minute interval [start, end).
    """
    if not grid.get("rush_hour_eligible"):
        return Decimal("0.00")
    now = store().now()
    dow = DAY_OF_WEEK_MAP[now.weekday()]
    minute_of_day = now.hour * 60 + now.minute

    for w in store().list_collection("rush_hour_windows"):
        if not w.get("is_active"):
            continue
        if w["day_of_week"] != dow:
            continue
        if w["start_minute"] <= minute_of_day < w["end_minute"]:
            return Decimal(str(w["additive_bonus"]))
    return Decimal("0.00")


def quoted_fare_for(ride: Dict[str, Any], pickup_grid: Dict[str, Any]) -> None:
    """Compute base_fare_cents, pickup_multiplier_snapshot, rush_hour_bonus_snapshot, quoted_fare_cents.

    Mutates `ride` in place.
    """
    base = base_fare_cents_for(ride["distance_km"])
    pickup_mult = pickup_grid["current_multiplier"]
    if not isinstance(pickup_mult, Decimal):
        pickup_mult = Decimal(str(pickup_mult))
    bonus = find_active_rush_hour_bonus(pickup_grid)

    eff = pickup_mult + bonus
    if eff > MULTIPLIER_CAP:
        eff = MULTIPLIER_CAP

    quoted = round_half_up_int(Decimal(base) * eff)
    ride["base_fare_cents"] = base
    ride["pickup_multiplier_snapshot"] = round_half_up_decimal(pickup_mult, 2)
    ride["rush_hour_bonus_snapshot"] = round_half_up_decimal(bonus, 2)
    ride["quoted_fare_cents"] = quoted


def final_fare_for(ride: Dict[str, Any], pickup_grid: Dict[str, Any]) -> None:
    """Compute final_fare_cents (chronological variant) + driver_earnings_cents.

    Mutates ride. Two-step rounding in fixed order:
      1) final_fare_cents = round_half_up(base_fare_cents * eff_mult_final)
      2) driver_earnings_cents = round_half_up(final_fare_cents * (1 - fee))
    """
    live_pickup_mult = pickup_grid["current_multiplier"]
    if not isinstance(live_pickup_mult, Decimal):
        live_pickup_mult = Decimal(str(live_pickup_mult))
    live_bonus = find_active_rush_hour_bonus(pickup_grid)

    eff = live_pickup_mult + live_bonus
    if eff > MULTIPLIER_CAP:
        eff = MULTIPLIER_CAP

    final_fare = round_half_up_int(Decimal(ride["base_fare_cents"]) * eff)
    earnings = round_half_up_int(Decimal(final_fare) * (Decimal("1") - PLATFORM_FEE_RATE))

    ride["final_fare_cents"] = final_fare
    ride["driver_earnings_cents"] = earnings


def clawback_for_refund(approved_refund_cents: int) -> int:
    """Driver-share clawback: round_half_up(approved_refund_cents * (1 - PLATFORM_FEE_RATE))."""
    return round_half_up_int(Decimal(approved_refund_cents) * (Decimal("1") - PLATFORM_FEE_RATE))
