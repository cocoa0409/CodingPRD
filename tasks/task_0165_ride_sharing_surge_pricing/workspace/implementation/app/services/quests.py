"""Quest bonus lifecycle + overlap checks."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..store import store
from ..util import round_half_up_int


def quest_intervals_overlap_closed(a_start, a_end, b_start, b_end) -> bool:
    """Closed-closed overlap semantics — adjacency at endpoint instants counts as overlap.

    PRD §3.6 — quest enrollment overlap uses CLOSED intervals.
    """
    return a_start <= b_end and b_start <= a_end


def find_overlapping_quest_for_driver(driver_id: str, new_quest: Dict[str, Any], exclude_quest_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Check if driver is already enrolled in another quest whose closed window overlaps new_quest."""
    s = store()
    for d in s.list_collection("drivers"):
        if d["id"] != driver_id:
            continue
        cur_qid = d.get("quest_id")
        if not cur_qid:
            return None
        if exclude_quest_id and cur_qid == exclude_quest_id:
            return None
        cur_q = s.quest_bonuses.get(cur_qid)
        if not cur_q:
            return None
        if quest_intervals_overlap_closed(
            cur_q["window_start"], cur_q["window_end"],
            new_quest["window_start"], new_quest["window_end"],
        ):
            return cur_q
        return None
    return None


def quest_completed_rides_count(driver_id: str, quest: Dict[str, Any]) -> int:
    """Count COMPLETED rides for driver_id whose completed_at ∈ [window_start, window_end)."""
    s = store()
    ws = quest["window_start"]
    we = quest["window_end"]
    n = 0
    for r in s.list_collection("rides"):
        if r["status"] != "COMPLETED":
            continue
        if r["driver_id"] != driver_id:
            continue
        ca = r.get("completed_at")
        if ca is None:
            continue
        if ws <= ca < we:
            n += 1
    return n


def transition_quests_for_clock(new_time) -> None:
    """When clock advances to new_time, walk quests and apply SCHEDULED→ACTIVE→CLOSED transitions.

    On ACTIVE→CLOSED, pay out bonuses to enrolled drivers whose quest_completed_rides >= target.
    Idempotent via 'bonus_paid' flag on quest.
    """
    s = store()
    # Snapshot ordered quest list to avoid mutation during iteration
    quests = list(s.list_collection("quest_bonuses"))
    for q in quests:
        # SCHEDULED -> ACTIVE
        if q["status"] == "SCHEDULED" and new_time >= q["window_start"]:
            q["status"] = "ACTIVE"
            q["updated_at"] = new_time
            q["version"] += 1
        # ACTIVE -> CLOSED
        if q["status"] == "ACTIVE" and new_time >= q["window_end"]:
            # Recompute final quest_completed_rides for each enrolled driver, then pay bonuses.
            if not q.get("bonus_paid"):
                for d in s.list_collection("drivers"):
                    if d.get("quest_id") == q["id"]:
                        # Refresh count
                        cnt = quest_completed_rides_count(d["id"], q)
                        d["quest_completed_rides"] = cnt
                        if cnt >= q["target_ride_count"]:
                            d["total_earnings_cents"] += q["bonus_amount_cents"]
                            d["updated_at"] = new_time
                            d["version"] += 1
                q["bonus_paid"] = True
            q["status"] = "CLOSED"
            q["updated_at"] = new_time
            q["version"] += 1
