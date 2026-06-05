"""Demurrage charge calculation (SCAFFOLD §1.3 demurrage_charge, PRD §3.6).

Chronological day-bucket (marginal-tier) variant. Returns (chargeable_days,
total_cents). The free-time boundary is exclusive: a container as-of exactly
free_time_expires_at owes 0.
"""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

import db
from db import (
    TIER1_DAYS,
    TIER1_RATE_CENTS,
    TIER2_DAYS,
    TIER2_RATE_CENTS,
    TIER3_RATE_CENTS,
)
from services.common import clock_dt, format_dt, parse_dt


def free_time_expires_at(container: Dict[str, Any]) -> Optional[str]:
    """Computed free-time expiry (PRD §3.3): actual_berth_at + free_time_days,
    or null until the discharge window has berthed.

    Derived from the discharge window's actual_berth_at so it is correct for
    containers declared before OR after the window was berthed, and reverts to
    null automatically when the window is unberthed (actual_berth_at cleared).
    """
    window = db.berth_windows.get(container.get("berth_window_id"))
    if window is None:
        return None
    berthed_at = window.get("actual_berth_at")
    if berthed_at is None:
        return None
    vessel = db.vessels.get(container.get("vessel_id"))
    days = vessel["free_time_days"] if vessel else 0
    return format_dt(parse_dt(berthed_at) + timedelta(days=days))


def _rate_for_day(d: int) -> int:
    """Marginal per-day rate for chargeable-day index d (1-based)."""
    if d <= TIER1_DAYS:
        return TIER1_RATE_CENTS
    if d <= TIER1_DAYS + TIER2_DAYS:
        return TIER2_RATE_CENTS
    return TIER3_RATE_CENTS


def compute(container: Dict[str, Any]) -> Tuple[int, int]:
    """Return (chargeable_days, total_cents) as of the current logical clock."""
    expires = free_time_expires_at(container)
    if expires is None:
        return 0, 0
    expires_dt = parse_dt(expires)
    as_of = clock_dt()
    if as_of <= expires_dt:
        return 0, 0
    elapsed_seconds = (as_of - expires_dt).total_seconds()
    chargeable_days = math.ceil(elapsed_seconds / 86400.0)
    if chargeable_days <= 0:
        return 0, 0
    total = 0
    for d in range(1, chargeable_days + 1):
        total += _rate_for_day(d)
    return chargeable_days, total
