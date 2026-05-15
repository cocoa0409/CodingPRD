"""Cabinet capacity-stats recomputation (PRD §3.7)."""
from __future__ import annotations

from typing import Any

from ..calculations import level_for, max_severity, percent_round_half_up_2dp
from ..store import bump_version, get_store


SIZE_CLASSES = ("SMALL", "MEDIUM", "LARGE")


def recompute_cabinet_capacity(cabinet: dict[str, Any], *, bump: bool = True) -> None:
    """Recompute every derived capacity field on `cabinet` from its compartments.

    If `bump` is True we also refresh `updated_at` and increment `version`.
    """
    store = get_store()
    comps = [c for c in store.compartments.values() if c["cabinet_id"] == cabinet["id"]]

    # Totals per size class
    totals = {sz: 0 for sz in SIZE_CLASSES}
    occupied = {sz: 0 for sz in SIZE_CLASSES}

    for c in comps:
        sz = c["size_class"]
        if sz in totals:
            totals[sz] += 1
            if c["occupancy_status"] in ("RENTED", "OVERDUE"):
                occupied[sz] += 1

    cabinet["small_capacity_total"] = totals["SMALL"]
    cabinet["medium_capacity_total"] = totals["MEDIUM"]
    cabinet["large_capacity_total"] = totals["LARGE"]
    cabinet["total_compartments"] = sum(totals.values())

    cabinet["small_occupancy_pct"] = percent_round_half_up_2dp(occupied["SMALL"], totals["SMALL"])
    cabinet["medium_occupancy_pct"] = percent_round_half_up_2dp(occupied["MEDIUM"], totals["MEDIUM"])
    cabinet["large_occupancy_pct"] = percent_round_half_up_2dp(occupied["LARGE"], totals["LARGE"])

    cabinet["capacity_alert_level"] = max_severity(
        level_for(cabinet["small_occupancy_pct"]),
        level_for(cabinet["medium_occupancy_pct"]),
        level_for(cabinet["large_occupancy_pct"]),
    )

    if bump:
        bump_version(cabinet)
