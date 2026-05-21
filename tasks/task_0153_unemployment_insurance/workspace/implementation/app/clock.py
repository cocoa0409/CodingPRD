"""Virtual SystemClock service. Single-row singleton initialised on first read.

The clock is advanced via POST /_clock/advance by N seconds. Time-sensitive
state transitions (PandemicExtension activation, benefit-year close, appeal
deadlines) are processed by services/sweep.run_sweep() each time the clock
advances.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .store import get_store
from .util import format_iso8601, parse_iso8601


def _init_now() -> str:
    store = get_store()
    if not store.system_clock_now:
        store.system_clock_now = format_iso8601(datetime.now(tz=timezone.utc))
    return store.system_clock_now


def now_iso() -> str:
    return _init_now()


def now_dt() -> datetime:
    s = _init_now()
    dt = parse_iso8601(s)
    if dt is None:
        # Should be impossible; fallback to real time.
        dt = datetime.now(tz=timezone.utc)
    return dt


def set_now(dt: datetime) -> None:
    store = get_store()
    store.system_clock_now = format_iso8601(dt)


def advance_seconds(seconds: int) -> datetime:
    current = now_dt()
    new_dt = current + timedelta(seconds=seconds)
    set_now(new_dt)
    return new_dt
