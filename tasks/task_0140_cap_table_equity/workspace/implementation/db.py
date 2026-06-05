"""In-memory data store. All state vanishes on process restart.

The store starts EMPTY on every boot. Nothing is seeded or preloaded; every
entity is constructed by tests through the declared API surface.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


# Entity dictionaries: id -> entity dict
cap_tables: dict = {}
security_classes: dict = {}
shareholders: dict = {}
share_issuances: dict = {}
valuations: dict = {}
option_pools: dict = {}
option_grants: dict = {}
exercises: dict = {}
section_83b_elections: dict = {}
safe_notes: dict = {}
forms_3921: dict = {}
liquidation_events: dict = {}
waterfall_distributions: dict = {}
blackout_windows: dict = {}

# Pinned clock (set via POST /_clock/set_current_utc). None => use real UTC.
_clock_pin: Optional[datetime] = None


def reset() -> None:
    global _clock_pin
    for store in (
        cap_tables, security_classes, shareholders, share_issuances, valuations,
        option_pools, option_grants, exercises, section_83b_elections, safe_notes,
        forms_3921, liquidation_events, waterfall_distributions, blackout_windows,
    ):
        store.clear()
    _clock_pin = None


def now_utc() -> datetime:
    """Return the pinned test clock when set, else real UTC."""
    if _clock_pin is not None:
        return _clock_pin
    return datetime.now(tz=timezone.utc)


def set_clock(dt: datetime) -> None:
    global _clock_pin
    _clock_pin = dt
