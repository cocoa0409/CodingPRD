"""Computed-field recalculations and cross-entity cascade helpers."""
from __future__ import annotations

from typing import Optional

from pv_ops.store import Store
from pv_ops.utils import D, round_half_up


def recompute_station_operational_status(store: Store, station: dict) -> None:
    """Apply the station_operational_status calculation in-place and bump."""
    station_id = station["id"]
    total = 0
    under = 0
    for inv in store.inverters.values():
        if inv.get("station_id") != station_id:
            continue
        ls = inv.get("lifecycle_state")
        if ls in ("OPERATING", "UNDER_REPAIR"):
            total += 1
            if ls == "UNDER_REPAIR":
                under += 1

    prior = station.get("operational_status")
    if total == 0:
        new_status = "OPERATIONAL"
    else:
        ratio = D(under) / D(total)
        if ratio >= D("0.50"):
            new_status = "OUT_OF_SERVICE"
        elif ratio >= D("0.20"):
            new_status = "DEGRADED"
        else:
            new_status = "OPERATIONAL"

    if new_status != prior:
        station["operational_status"] = new_status
        store.bump(station)


def recompute_array_string_count(store: Store, array: dict) -> None:
    array_id = array["id"]
    array["string_count"] = sum(
        1 for s in store.strings.values() if s.get("array_id") == array_id
    )


def recompute_string_rated_dc(store: Store, pvstring: dict) -> None:
    string_id = pvstring["id"]
    total_w = D(0)
    for m in store.modules.values():
        if m.get("string_id") == string_id and m.get("lifecycle_state") == "INSTALLED":
            total_w += D(m.get("wp_rating", 0))
    # rated_dc_power_kw in kW
    rated_kw = round_half_up(total_w / D(1000), 3)
    pvstring["rated_dc_power_kw"] = float(rated_kw)


def station_for(store: Store, station_id: str) -> Optional[dict]:
    return store.stations.get(station_id)
