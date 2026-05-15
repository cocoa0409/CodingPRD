"""Zone posture and bin status roll-up. PRD §2.10, §3.3."""
from __future__ import annotations

from typing import Any

from ..store import bump_version, get_store


def open_deviations_for_zone(zone_id: str) -> list[dict[str, Any]]:
    store = get_store()
    return [
        d
        for d in store.deviations.values()
        if d["zone_id"] == zone_id and d["status"] != "CLOSED_ASSESSED"
    ]


def child_bins(zone_id: str) -> list[dict[str, Any]]:
    store = get_store()
    return [b for b in store.bins.values() if b["zone_id"] == zone_id]


def recompute_zone_utilization(zone_id: str) -> None:
    """Roll up zone.utilization_units = sum(bin.occupied_volume)."""
    store = get_store()
    zone = store.zones.get(zone_id)
    if not zone:
        return
    total = sum(int(b.get("occupied_volume", 0) or 0) for b in child_bins(zone_id))
    if zone.get("utilization_units") != total:
        zone["utilization_units"] = total
        bump_version(zone)


def recompute_zone_posture(zone_id: str) -> None:
    """Derive `current_posture` purely from currently open deviations on the zone (§2.10, §3.3).

    - Any open deviation with an ALARM_* event → FROZEN
    - Otherwise any open MINOR-classified deviation → RESTRICTED (warning-only)
    - All deviations closed-assessed → OPEN

    Also flips child bin status: FROZEN→LOCKED; otherwise → AVAILABLE/OCCUPIED.
    """
    store = get_store()
    zone = store.zones.get(zone_id)
    if not zone:
        return
    open_devs = open_deviations_for_zone(zone_id)

    # Determine if any of those involve alarm-level events.
    has_alarm = False
    for d in open_devs:
        for ev in store.temperature_events.values():
            if ev.get("deviation_id") == d["id"] and ev.get("kind") in ("ALARM_LOW", "ALARM_HIGH"):
                has_alarm = True
                break
        if has_alarm:
            break

    if has_alarm:
        new_posture = "FROZEN"
    elif open_devs:
        new_posture = "RESTRICTED"
    else:
        new_posture = "OPEN"

    posture_changed = zone.get("current_posture") != new_posture
    if posture_changed:
        zone["current_posture"] = new_posture
        bump_version(zone)

    # Cascade bin.status changes.
    bins = child_bins(zone_id)
    for b in bins:
        if new_posture == "FROZEN":
            target_status = "LOCKED"
        else:
            target_status = "OCCUPIED" if b.get("current_lot_id") else "AVAILABLE"
        if b.get("status") != target_status:
            b["status"] = target_status
            bump_version(b)


def recompute_after_bin_change(zone_id: str) -> None:
    """Run after any bin field changed: zone utilization and posture."""
    recompute_zone_utilization(zone_id)
    recompute_zone_posture(zone_id)
