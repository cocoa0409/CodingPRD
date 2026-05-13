"""Queue management: join, abandon, promote."""

from __future__ import annotations

import db


def waiting_entries_at_station(station_id: str) -> list[dict]:
    """Return WAITING queue entries at the station ordered by position."""
    entries = [
        q for q in db.queue_entries.values()
        if q["station_id"] == station_id and q["status"] == "WAITING"
    ]
    entries.sort(key=lambda q: (q["position"], q["enqueued_at"], q["id"]))
    return entries


def waiting_count(station_id: str) -> int:
    return len(waiting_entries_at_station(station_id))


def decrement_positions_after(station_id: str, removed_position: int) -> None:
    """After a WAITING entry leaves at `removed_position`, decrement higher positions."""
    for q in db.queue_entries.values():
        if (
            q["station_id"] == station_id
            and q["status"] == "WAITING"
            and q["position"] > removed_position
        ):
            q["position"] -= 1
            db.bump(q)


def station_has_idle_pile(station_id: str) -> bool:
    for p in db.piles.values():
        if (
            p["station_id"] == station_id
            and p["lifecycle_state"] == "ON_SHELF"
            and p["operational_state"] == "IDLE"
        ):
            return True
    return False


def promote_if_possible(station_id: str) -> dict | None:
    """If an idle pile is available at station and there is a WAITING entry at
    position 1, promote it.  Returns the promoted entry or None."""
    waiting = waiting_entries_at_station(station_id)
    if not waiting:
        return None
    if not station_has_idle_pile(station_id):
        return None
    candidate = waiting[0]
    if candidate["position"] != 1:
        return None
    candidate["status"] = "PROMOTED"
    db.bump(candidate)
    decrement_positions_after(station_id, candidate["position"])
    return candidate
