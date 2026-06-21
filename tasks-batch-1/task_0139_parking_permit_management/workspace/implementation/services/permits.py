"""Permit + waitlist promotion cascades (PRD §3.3, §3.4)."""
from __future__ import annotations

from typing import Any, Dict, Optional

import db
from services import recompute


def promote_lowest_waiting(zone: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Promote the lowest-sequence WAITING entry for this zone, if any.

    Promotion creates a brand-new REQUESTED Permit (copying zone/motorist/plate),
    sets the entry PROMOTED + promoted_permit_id, and bumps the entry's version.
    Promotion does NOT activate the new permit and does NOT change the zone's
    permits_active_count (PRD §3.4). The caller is responsible for the capacity
    guard. Returns the promoted entry, or None if no WAITING entry exists.
    """
    waiting = [
        w
        for w in db.waitlist_entries.values()
        if w["zone_id"] == zone["id"] and w["status"] == "WAITING"
    ]
    if not waiting:
        return None
    entry = min(waiting, key=lambda w: w["sequence"])

    new_permit = db.stamp_common(
        {
            "zone_id": entry["zone_id"],
            "motorist_id": entry["motorist_id"],
            "plate": entry["plate"],
            "status": "REQUESTED",
            "valid_from_utc": None,
            "valid_until_utc": None,
            "monthly_fee_charged_cents": 0,
        }
    )
    db.permits[new_permit["id"]] = new_permit

    entry["status"] = "PROMOTED"
    entry["promoted_permit_id"] = new_permit["id"]
    db.bump(entry)
    return entry


def free_slot_and_promote(zone: Dict[str, Any]) -> None:
    """After a revoke/expire frees a slot: recompute the zone's active count
    (which bumps the zone), then auto-promote the lowest WAITING entry if a slot
    is now free (PRD §3.3 / §3.4, cascade T1)."""
    recompute.recompute_zone_active_permits(zone, bump=True)
    if zone["permits_active_count"] < zone["permit_capacity"]:
        promote_lowest_waiting(zone)
