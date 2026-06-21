"""Fare, fine, and report calculations (scaffold §1.3, PRD §3.3–3.8).

All monetary amounts are integer cents. Where a fractional cent arises (slow-zone
discount, low-income fine reduction) the result is rounded half-up to a whole
cent before being combined with any other amount (PRD §2.6).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

import constants
from db import db
from services import zone as zone_svc
from util import round_half_up_cents


def _ceil_seconds_to_minutes(total_seconds):
    """sum-seconds-then-ceil (PRD §3.4): 0 seconds => 0 minutes."""
    if total_seconds <= 0:
        return 0
    return math.ceil(total_seconds / constants.SECONDS_PER_MINUTE)


def trip_billable_minutes(trip):
    """Sum whole seconds across closed RIDE segments, then ceil (PRD §3.4).

    Rounding order is PINNED: sum-seconds-then-ceil, NOT ceil-each-then-sum.
    """
    ride_seconds = 0
    for seg in _segments_of(trip):
        if seg["segment_type"] == "RIDE" and seg.get("ended_at") is not None:
            ride_seconds += seg["duration_seconds"]
    return _ceil_seconds_to_minutes(ride_seconds)


def trip_final_fare(trip, plan):
    """Final chronological fare from actual RIDE segments (PRD §3.5).

    Partition billable seconds into SLOW vs non-SLOW buckets by each RIDE
    segment's zone_id, ceil each bucket independently, then:
      normal_charge = normal_minutes * per_minute_cents
      slow_charge   = round_half_up(slow_minutes * per_minute_cents * (1 - discount))
      gross         = unlock_fee_cents + normal_charge + slow_charge
      final         = gross if daily_cap_cents == 0 else min(gross, daily_cap_cents)
    """
    slow_seconds = 0
    normal_seconds = 0
    for seg in _segments_of(trip):
        if seg["segment_type"] != "RIDE" or seg.get("ended_at") is None:
            continue
        if zone_svc.is_slow(seg.get("zone_id")):
            slow_seconds += seg["duration_seconds"]
        else:
            normal_seconds += seg["duration_seconds"]

    slow_minutes = _ceil_seconds_to_minutes(slow_seconds)
    normal_minutes = _ceil_seconds_to_minutes(normal_seconds)

    per_minute = plan["per_minute_cents"]
    normal_charge = normal_minutes * per_minute
    discount = Decimal(str(plan.get("slow_zone_discount_pct", 0)))
    slow_charge_raw = Decimal(slow_minutes) * Decimal(per_minute) * (Decimal(1) - discount)
    slow_charge = int(slow_charge_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    gross = plan["unlock_fee_cents"] + normal_charge + slow_charge
    cap = plan["daily_cap_cents"]
    if cap == 0:
        return gross
    return min(gross, cap)


def trip_provisional_fare(plan):
    """Forward-looking estimate at unlock (PRD §3.3).

    estimate = unlock_fee_cents + PROJECTED_TRIP_MINUTES * per_minute_cents,
    capped to daily_cap_cents when the cap is > 0.
    """
    estimate = plan["unlock_fee_cents"] + constants.PROJECTED_TRIP_MINUTES * plan["per_minute_cents"]
    cap = plan["daily_cap_cents"]
    if cap == 0:
        return estimate
    return min(estimate, cap)


def fine_amount(rider_plan):
    """Parking-fine penalty (PRD §3.5).

    base = BASE_PARKING_FINE_CENTS; LOW_INCOME riders pay base reduced by 40%,
    rounded half-up to a whole cent.
    """
    base = constants.BASE_PARKING_FINE_CENTS
    if rider_plan["code"] == "LOW_INCOME":
        reduced = Decimal(base) * (Decimal(1) - Decimal(str(constants.LOW_INCOME_FINE_DISCOUNT_PCT)))
        return int(reduced.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return base


def _segments_of(trip):
    return [s for s in db.trip_segments.values() if s["trip_id"] == trip["id"]]
