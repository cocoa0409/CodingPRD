"""Rush-hour window overlap checks."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..store import store


def rush_hour_overlap_half_open(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open intervals [start, end) — adjacency at boundary is NOT overlap."""
    # Overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


def find_overlapping_rush_hour(day_of_week: str, start_minute: int, end_minute: int,
                                exclude_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    s = store()
    for w in s.list_collection("rush_hour_windows"):
        if exclude_id and w["id"] == exclude_id:
            continue
        if not w.get("is_active"):
            continue
        if w["day_of_week"] != day_of_week:
            continue
        if rush_hour_overlap_half_open(start_minute, end_minute, w["start_minute"], w["end_minute"]):
            return w
    return None
