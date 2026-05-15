"""Subscription-related helpers."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from app.clock import logical_clock
from app.store import store
from app.utils import format_iso, parse_iso


CYCLE_DAYS = {"WEEKLY": 7, "BIWEEKLY": 14, "MONTHLY": 30}


def derive_cycle_days(frequency: str) -> int:
    return CYCLE_DAYS[frequency]


def get_next_scheduled_order(subscription_id: str) -> Optional[Dict[str, Any]]:
    """Return the earliest SCHEDULED order for this subscription (by scheduled_ship_at)."""
    candidates = [
        o
        for o in store.orders.values()
        if o.get("subscription_id") == subscription_id and o.get("fulfillment_status") == "SCHEDULED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda o: (o.get("scheduled_ship_at", ""), o.get("id", "")))
    return candidates[0]


def compute_next_cycle_iso(from_dt=None, cycle_days: int = 7) -> str:
    from_dt = from_dt or logical_clock.now()
    return format_iso(from_dt + timedelta(days=cycle_days))
