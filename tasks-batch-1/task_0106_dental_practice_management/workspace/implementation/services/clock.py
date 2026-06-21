"""The deterministic logical clock (PRD §3.9).

A single process-global instant that FrontDesk / BillingSpecialist set via
POST /_clock/set. Waiting periods, frequency gaps, recare due dates, and
predetermination expiry all read this clock as "now".

Default (before any /_clock/set) is the real wall-clock UTC instant, so that
time-based reads have a sensible "now" even if a test never sets the clock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_clock = {"now": None}  # type: ignore[var-annotated]


def set_now(iso_str: str) -> None:
    _clock["now"] = parse_dt(iso_str)


def now() -> datetime:
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return _clock["now"].isoformat() if _clock["now"] is not None else datetime.now(timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 datetime (accepts trailing 'Z')."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value: str):
    """Parse an ISO calendar date (YYYY-MM-DD) into a date object."""
    return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
