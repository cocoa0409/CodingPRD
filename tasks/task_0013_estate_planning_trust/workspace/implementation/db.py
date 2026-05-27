"""In-memory data store. All state vanishes on process restart."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


# Entity dictionaries: id -> entity dict
decedents: dict = {}
estates: dict = {}
assets: dict = {}
beneficiary_designations: dict = {}
executors: dict = {}
powers_of_attorney: dict = {}
directives: dict = {}
guardianships: dict = {}
creditor_claims: dict = {}
probate_orders: dict = {}

# Pinned clock (set via POST /_clock/set_current_utc). None => use real UTC.
_clock_pin: Optional[datetime] = None


def reset() -> None:
    """Clear every store. Used in test harness restarts -- but the harness
    relaunches the process, so this is mostly belt-and-suspenders."""
    global _clock_pin
    decedents.clear()
    estates.clear()
    assets.clear()
    beneficiary_designations.clear()
    executors.clear()
    powers_of_attorney.clear()
    directives.clear()
    guardianships.clear()
    creditor_claims.clear()
    probate_orders.clear()
    _clock_pin = None


def now_utc() -> datetime:
    """Return the system clock or the pinned clock when set."""
    if _clock_pin is not None:
        return _clock_pin
    return datetime.now(tz=timezone.utc)


def set_clock(dt: datetime) -> None:
    global _clock_pin
    _clock_pin = dt
