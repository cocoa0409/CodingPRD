"""Driver selection policy per PRD §3.3 / scaffold §1.3 driver_selection."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..store import store
from .queue import queue_rows_for_grid


def _grid_numeric(code: str) -> Optional[int]:
    """Numeric portion of a grid code 'G-NNN'. Returns None if malformed."""
    if not isinstance(code, str):
        return None
    if not code.startswith("G-"):
        return None
    rest = code[2:]
    if not rest.isdigit():
        return None
    return int(rest)


def _adjacent_grid_codes(pickup_code: str) -> List[str]:
    """All grid codes whose numeric portion differs from pickup_code by exactly 1."""
    pivot = _grid_numeric(pickup_code)
    if pivot is None:
        return []
    out = []
    for g in store().list_collection("grids"):
        n = _grid_numeric(g["code"])
        if n is None:
            continue
        if abs(n - pivot) == 1:
            out.append(g["code"])
    return out


def select_driver(pickup_grid: Dict[str, Any], allow_neighbor_grid: bool) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Apply the deterministic driver selection policy.

    Returns (selected_driver_dict, picked_from_airport_queue).
    """
    s = store()
    pickup_code = pickup_grid["code"]

    # Airport branch first.
    if pickup_grid.get("is_airport"):
        rows = queue_rows_for_grid(pickup_code)
        if rows:
            head = rows[0]
            driver = s.drivers.get(head["driver_id"])
            if driver is not None:
                return driver, True
        # Fallback through to non-airport branch in same grid.

    candidates = [
        d for d in s.list_collection("drivers")
        if d["status"] == "AVAILABLE" and d["current_grid_code"] == pickup_code
    ]
    if candidates:
        # ORDER BY updated_at ASC, tie-break by Driver.id ASC
        candidates.sort(key=lambda d: (d["updated_at"], d["id"]))
        return candidates[0], False

    if allow_neighbor_grid:
        adj_codes = set(_adjacent_grid_codes(pickup_code))
        neighbor_candidates = [
            d for d in s.list_collection("drivers")
            if d["status"] == "AVAILABLE" and d["current_grid_code"] in adj_codes
        ]
        if neighbor_candidates:
            neighbor_candidates.sort(key=lambda d: (d["updated_at"], d["id"]))
            return neighbor_candidates[0], False

    return None, False
