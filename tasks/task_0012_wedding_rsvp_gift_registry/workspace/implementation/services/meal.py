"""Meal-count aggregation (scaffold §1.3 meal_count_aggregation, PRD §3.4)."""
from __future__ import annotations

from typing import Optional

import db


def meal_count(wedding_id: str, meal_option_id: str,
               exclude_guest_id: Optional[str] = None,
               exclude_plus_one_id: Optional[str] = None) -> int:
    """Count ATTENDING guests + ATTENDING plus-ones of this wedding whose
    meal_option_id == meal_option_id.

    The exclude_* arguments are used when checking a proposed change for a
    specific guest/plus-one whose contribution to the *current* count must
    be subtracted (e.g. when changing meal selection).
    """
    n = 0
    for guest in db.guests.values():
        if guest.get("wedding_id") != wedding_id:
            continue
        if exclude_guest_id is not None and guest.get("id") == exclude_guest_id:
            continue
        if guest.get("rsvp_status") != "ATTENDING":
            continue
        if guest.get("meal_option_id") == meal_option_id:
            n += 1
    for po in db.plus_ones.values():
        if po.get("wedding_id") != wedding_id:
            continue
        if exclude_plus_one_id is not None and po.get("id") == exclude_plus_one_id:
            continue
        if po.get("rsvp_status") != "ATTENDING":
            continue
        if po.get("meal_option_id") == meal_option_id:
            n += 1
    return n


def meal_summary(wedding_id: str) -> dict:
    """Return { items: [...], total_attendees: int } for a wedding."""
    items = []
    total = 0
    # Order MealOptions by created_at for a stable ordering.
    options = [m for m in db.meal_options.values() if m.get("wedding_id") == wedding_id]
    options.sort(key=lambda m: m.get("created_at", ""))
    for m in options:
        c = meal_count(wedding_id, m["id"])
        items.append({
            "meal_option_id": m["id"],
            "code": m["code"],
            "label": m["label"],
            "is_kids": m["is_kids"],
            "max_servings": m["max_servings"],
            "count": c,
        })
        total += c
    return {"items": items, "total_attendees": total}
