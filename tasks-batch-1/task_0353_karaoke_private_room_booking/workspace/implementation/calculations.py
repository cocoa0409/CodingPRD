"""Calculation rules (PRD §3.3, §3.4 / scaffold §1.3).

Monetary precision (PRD §2.6): integer cents, exact rational accumulation,
sum-then-round-once, round-half-up. Per-minute base rate = hourly/60, never
rounded early. Decimal is used throughout; float is never used for money.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

import db
import helpers

MINUTES_PER_HOUR = Decimal(60)
OVERAGE_MULTIPLIER = Decimal("2.0")


def round_half_up(value):
    """Round an exact Decimal to whole cents, half-up (PRD §2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _local_minute_of_day(dt_utc, tz_name):
    """Local minute-of-day (0..1439) for a UTC instant in the venue timezone."""
    if ZoneInfo is not None:
        try:
            local = dt_utc.astimezone(ZoneInfo(tz_name))
        except Exception:
            local = dt_utc
    else:  # pragma: no cover
        local = dt_utc
    return local.hour * 60 + local.minute


def _is_peak(dt_utc, venue):
    """A minute is peak when its local minute-of-day is in [start, end) (PRD §2.9)."""
    mod = _local_minute_of_day(dt_utc, venue["timezone"])
    return venue["peak_start_minute"] <= mod < venue["peak_end_minute"]


def _whole_minutes_between(start_utc, end_utc):
    """Number of whole minutes in [start, end). Floor of the second delta / 60."""
    if end_utc <= start_utc:
        return 0
    delta = end_utc - start_utc
    return int(delta.total_seconds() // 60)


# --- quoted_room_subtotal (forward-looking) ----------------------------------

def quoted_room_subtotal(reservation, venue, room_type, group_package):
    """Forward-looking quote priced over the booked interval (PRD §3.3).

    Package case: simply the package flat_price_cents (included hours / overage
    not charged at quote time). A la carte: peak/off-peak split over the booked
    interval, per-minute base = base_hourly_rate/60, sum-then-round once.
    """
    if group_package is not None:
        return int(group_package["flat_price_cents"])

    start = helpers.parse_stored_dt(reservation["slot_start_utc"])
    end = helpers.parse_stored_dt(reservation["slot_end_utc"])
    booked_minutes = _whole_minutes_between(start, end)

    per_min_base = Decimal(room_type["base_hourly_rate_cents"]) / MINUTES_PER_HOUR
    peak_mult = Decimal(str(venue["peak_multiplier"]))

    total = Decimal(0)
    cursor = start
    for _ in range(booked_minutes):
        rate = per_min_base
        if _is_peak(cursor, venue):
            rate = rate * peak_mult
        total += rate
        cursor = cursor + timedelta(minutes=1)

    return round_half_up(total)


# --- settled_room_subtotal (chronological) -----------------------------------

def settled_room_subtotal(reservation, venue, room_type, group_package):
    """Chronological settlement over the actually occupied interval (PRD §3.4).

    Walk each whole minute of [checked_in_at, actual_end_utc):
      base = base_hourly_rate/60 (exact);
      * peak_multiplier if minute's local minute-of-day in [peak_start,peak_end);
      * OVERAGE_MULTIPLIER (2.0) if minute is at/after slot_end + overage_grace.
    Package case: first round(included_hours*60) minutes from checked_in_at are
    free; bill the rest; subtotal = flat_price_cents + round_half_up(rest).
    A la carte: round_half_up(sum of all exact per-minute rates).
    """
    checked_in = helpers.parse_stored_dt(reservation["checked_in_at"])
    actual_end = helpers.parse_stored_dt(reservation["actual_end_utc"])
    slot_end = helpers.parse_stored_dt(reservation["slot_end_utc"])

    overage_threshold = slot_end + timedelta(minutes=venue["overage_grace_minutes"])

    per_min_base = Decimal(room_type["base_hourly_rate_cents"]) / MINUTES_PER_HOUR
    peak_mult = Decimal(str(venue["peak_multiplier"]))

    total_minutes = _whole_minutes_between(checked_in, actual_end)

    covered_minutes = 0
    if group_package is not None:
        covered_minutes = round_half_up(
            Decimal(str(group_package["included_hours"])) * MINUTES_PER_HOUR
        )

    billed = Decimal(0)
    cursor = checked_in
    for idx in range(total_minutes):
        rate = per_min_base
        if _is_peak(cursor, venue):
            rate = rate * peak_mult
        if cursor >= overage_threshold:
            rate = rate * OVERAGE_MULTIPLIER
        if group_package is None or idx >= covered_minutes:
            billed += rate
        cursor = cursor + timedelta(minutes=1)

    if group_package is not None:
        return round_half_up(Decimal(group_package["flat_price_cents"]) + billed)
    return round_half_up(billed)


# --- fb figures (threshold) --------------------------------------------------

def fb_consumed_cents(reservation_id):
    """Sum of line_total_cents over PLACED FbOrders on the reservation (PRD §3.4)."""
    total = 0
    for order in db.fb_orders.values():
        if order["reservation_id"] == reservation_id and order["status"] == "PLACED":
            total += order["line_total_cents"]
    return total


def fb_shortfall_cents(reservation, room_type, group_package):
    """Shortfall charged only when effective F&B is STRICTLY below the floor (PRD §3.4)."""
    consumed = fb_consumed_cents(reservation["id"])
    credit = group_package["included_fb_credit_cents"] if group_package is not None else 0
    effective = consumed + credit
    required = room_type["fb_minimum_cents"]
    if effective < required:
        return required - effective
    return 0


# --- queue play_order (aggregation) ------------------------------------------

def recompute_play_order(reservation_id):
    """Assign 1-based play_order across PENDING entries sorted by
    (priority ASC, created_at ASC) (PRD §3.6). Each touched entry's
    updated_at/version is NOT bumped here — play_order is a derived/display
    field; only true status mutations bump version (per state-machine effects).
    """
    pending = [
        qe for qe in db.queue_entries.values()
        if qe["reservation_id"] == reservation_id and qe["status"] == "PENDING"
    ]
    pending.sort(key=lambda qe: (qe["priority"], qe["created_at"], qe["id"]))
    for i, qe in enumerate(pending, start=1):
        qe["play_order"] = i
    # Non-pending entries have no meaningful play position.
    for qe in db.queue_entries.values():
        if qe["reservation_id"] == reservation_id and qe["status"] != "PENDING":
            qe["play_order"] = None
