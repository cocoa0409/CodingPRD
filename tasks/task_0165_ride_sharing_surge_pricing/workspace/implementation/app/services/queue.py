"""Airport queue management."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..store import store


def queue_rows_for_grid(grid_code: str) -> List[Dict[str, Any]]:
    """All queue rows for a grid, sorted by position ASC."""
    rows = [r for r in store().list_collection("airport_queue") if r["grid_code"] == grid_code]
    rows.sort(key=lambda r: r["position"])
    return rows


def driver_in_any_queue(driver_id: str) -> Optional[Dict[str, Any]]:
    for r in store().list_collection("airport_queue"):
        if r["driver_id"] == driver_id:
            return r
    return None


def append_to_queue(grid_code: str, driver_id: str, row_id: str, joined_at, created_at) -> Dict[str, Any]:
    """Create a new queue row at the end (position = max + 1)."""
    s = store()
    rows = queue_rows_for_grid(grid_code)
    next_pos = (rows[-1]["position"] + 1) if rows else 1
    row = {
        "id": row_id,
        "grid_code": grid_code,
        "driver_id": driver_id,
        "position": next_pos,
        "joined_at": joined_at,
        "created_at": created_at,
    }
    s.insert("airport_queue", row)
    return row


def remove_from_queue(row_id: str) -> None:
    """Remove a queue row and renumber subsequent rows in the same grid."""
    s = store()
    if row_id not in s.airport_queue:
        return
    row = s.airport_queue[row_id]
    grid_code = row["grid_code"]
    removed_pos = row["position"]

    # Drop the row
    del s.airport_queue[row_id]
    if row_id in s.insertion_order["airport_queue"]:
        s.insertion_order["airport_queue"].remove(row_id)

    # Renumber later positions in same grid
    for r in s.airport_queue.values():
        if r["grid_code"] == grid_code and r["position"] > removed_pos:
            r["position"] -= 1


def head_of_queue(grid_code: str) -> Optional[Dict[str, Any]]:
    rows = queue_rows_for_grid(grid_code)
    return rows[0] if rows else None
