"""Surge multiplier recomputation per PRD §2.5 / scaffold §1.3 surge_multiplier."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from ..store import store
from ..util import round_half_up_decimal

MULTIPLIER_CAP = Decimal("3.00")
AIRPORT_SURCHARGE = Decimal("0.50")


def compute_surge_value(grid: Dict[str, Any]) -> Decimal:
    """Pure formula — no mutation."""
    active = grid["active_driver_count"]
    demand = grid["open_demand_count"]

    if active == 0 and demand == 0:
        raw = Decimal("1.00")
    elif active == 0:
        raw = MULTIPLIER_CAP
    else:
        ratio = Decimal(demand) / Decimal(active)
        if ratio <= Decimal("1.0"):
            raw = Decimal("1.00")
        elif ratio <= Decimal("2.0"):
            raw = Decimal("1.50")
        elif ratio <= Decimal("3.0"):
            raw = Decimal("2.00")
        elif ratio <= Decimal("4.0"):
            raw = Decimal("2.50")
        else:
            raw = MULTIPLIER_CAP

    if grid.get("is_airport"):
        raw = raw + AIRPORT_SURCHARGE

    capped = raw if raw < MULTIPLIER_CAP else MULTIPLIER_CAP
    return round_half_up_decimal(capped, 2)


def recompute_surge(grid: Dict[str, Any], bump_version: bool = True) -> None:
    """Recompute grid['current_multiplier']. Optionally bump version + updated_at.

    bump_version=False is used when the caller has already accounted for the version bump
    in the same logical mutation (e.g., grid creation).
    """
    grid["current_multiplier"] = compute_surge_value(grid)
    now = store().now()
    grid["last_surge_recomputed_at"] = now
    grid["updated_at"] = now
    if bump_version:
        grid["version"] += 1
