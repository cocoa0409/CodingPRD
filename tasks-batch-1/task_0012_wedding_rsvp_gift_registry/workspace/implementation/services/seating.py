"""Seating-chart waterfall allocation (scaffold §1.3 seating_chart_assignment)."""
from __future__ import annotations

from typing import Dict, List, Tuple

import db


def _build_attendee_list(wedding_id: str) -> List[Tuple[str, dict]]:
    """ATTENDING Guests ++ ATTENDING PlusOnes, sorted by (created_at ASC,
    full_name ASC).  Returns list of (assignee_type, row)."""
    guests = [g for g in db.guests.values()
              if g.get("wedding_id") == wedding_id and g.get("rsvp_status") == "ATTENDING"]
    plus_ones = [p for p in db.plus_ones.values()
                 if p.get("wedding_id") == wedding_id and p.get("rsvp_status") == "ATTENDING"]
    items: List[Tuple[str, dict]] = []
    for g in guests:
        items.append(("GUEST", g))
    for p in plus_ones:
        items.append(("PLUS_ONE", p))
    items.sort(key=lambda x: (x[1].get("created_at", ""), x[1].get("full_name", "")))
    return items


def _build_table_list(wedding_id: str) -> List[dict]:
    tables = [t for t in db.tables.values() if t.get("wedding_id") == wedding_id]
    tables.sort(key=lambda t: t.get("table_number", 0))
    return tables


def auto_seat_plan(wedding_id: str) -> dict:
    """Compute (deterministic) waterfall allocation. Returns
    { plan: [...], unseatable: [...] }. Does not mutate state.
    """
    attendees = _build_attendee_list(wedding_id)
    tables = _build_table_list(wedding_id)

    # Per-table running occupancy (start at 0 — we're planning fresh).
    table_count: Dict[str, int] = {t["id"]: 0 for t in tables}

    plan: List[dict] = []
    unseatable: List[dict] = []

    def kids_only_open() -> bool:
        for t in tables:
            if t.get("kids_only") and table_count[t["id"]] < int(t["capacity"]):
                return True
        return False

    for assignee_type, a in attendees:
        a_is_child = bool(a.get("is_child"))
        placed = False
        for t in tables:
            if table_count[t["id"]] >= int(t["capacity"]):
                continue
            if t.get("kids_only"):
                # kids_only table admits only children.
                if not a_is_child:
                    continue
            else:
                # non-kids_only table: admit adults always; admit children only
                # when every kids_only table is at capacity.
                if a_is_child:
                    if kids_only_open():
                        continue
            # placed.
            table_count[t["id"]] += 1
            plan.append({
                "assignee_type": assignee_type,
                "assignee_id": a["id"],
                "table_id": t["id"],
                "table_number": int(t["table_number"]),
            })
            placed = True
            break
        if not placed:
            unseatable.append({
                "assignee_type": assignee_type,
                "assignee_id": a["id"],
                "reason": "no_table_available",
            })

    return {"plan": plan, "unseatable": unseatable}
