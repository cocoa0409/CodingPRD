"""Calculation rules from SCAFFOLD/PRD §3."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict

from ..clock import now_utc
from ..timeutil import parse_date_local, parse_hhmm, park_local_to_utc

BOOKING_FEE_CENTS = 800
TAX_RATE = Decimal("0.08")
PROMOTION_HOLD_HOURS = 4


def _floor_cents(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def compute_booking_total(nightly_rate_cents: int, nights: int) -> dict:
    site_total = nightly_rate_cents * nights
    pre_tax = site_total + BOOKING_FEE_CENTS
    tax = _floor_cents(Decimal(pre_tax) * TAX_RATE)
    total = pre_tax + tax
    return {
        "nights": nights,
        "nightly_rate_cents": nightly_rate_cents,
        "total_fee_cents": total,
    }


def hours_between_now_and_utc(target_utc: datetime) -> float:
    now = now_utc()
    delta = (target_utc - now).total_seconds() / 3600.0
    return delta


def timed_entry_refund(entry_fee_cents: int, hours_to_entry: float) -> int:
    """Tiered refund per PRD §3.3."""
    if entry_fee_cents <= 0:
        return 0
    if hours_to_entry >= 168:
        return entry_fee_cents
    if hours_to_entry >= 48:
        return _floor_cents(Decimal(entry_fee_cents) * Decimal("0.5"))
    return 0


def campground_refund(
    *,
    total_fee_cents: int,
    nightly_rate_cents: int,
    hours_to_check_in: float,
    site_kind: str,
) -> int:
    """Tiered refund per PRD §3.4. site_kind: STANDARD or GROUP."""
    if site_kind == "GROUP":
        return max(0, total_fee_cents - BOOKING_FEE_CENTS - nightly_rate_cents)

    if hours_to_check_in >= 336:
        return max(0, total_fee_cents - BOOKING_FEE_CENTS)
    if hours_to_check_in >= 72:
        return _floor_cents(Decimal(total_fee_cents - BOOKING_FEE_CENTS) * Decimal("0.5"))
    if hours_to_check_in >= 24:
        return max(0, total_fee_cents - BOOKING_FEE_CENTS - nightly_rate_cents)
    return 0


def backcountry_refund(fee_cents: int, hours_to_entry: float) -> int:
    """Tiered refund per PRD §3.7."""
    if hours_to_entry >= 168:
        return fee_cents
    if hours_to_entry >= 24:
        return _floor_cents(Decimal(fee_cents) * Decimal("0.5"))
    return 0


def date_local_at_midnight_utc(date_local_str: str, tz_name: str) -> datetime:
    d = parse_date_local(date_local_str)
    if d is None:
        raise ValueError("invalid date_local")
    return park_local_to_utc(d.year, d.month, d.day, 0, 0, tz_name)


def date_local_at_hm_utc(date_local_str: str, hour: int, minute: int, tz_name: str) -> datetime:
    d = parse_date_local(date_local_str)
    if d is None:
        raise ValueError("invalid date_local")
    return park_local_to_utc(d.year, d.month, d.day, hour, minute, tz_name)


def hhmm_to_minutes(hhmm: str) -> int:
    parsed = parse_hhmm(hhmm)
    if parsed is None:
        raise ValueError("invalid HH:MM")
    h, m = parsed
    return h * 60 + m


def add_minutes_to_hhmm(hhmm: str, minutes: int) -> str:
    total = hhmm_to_minutes(hhmm) + minutes
    total_mod = total % 1440
    h = total_mod // 60
    m = total_mod % 60
    return f"{h:02d}:{m:02d}"
