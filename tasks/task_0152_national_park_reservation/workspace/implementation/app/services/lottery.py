"""Lottery draw and promotion-on-decline/forfeit logic (per PRD §3.6)."""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from ..errors import APIError
from ..store import get_store
from ..util import format_iso8601, parse_iso8601
from .common import stamp_update


MAX_STRIKES = 3
AWARD_EXPIRY_HOURS = 72


def _awarded_slots_used(permit_id: str) -> int:
    store = get_store()
    used = 0
    for a in store.lottery_applications.values():
        if a["lottery_permit_id"] != permit_id:
            continue
        if a["status"] in ("AWARDED", "ACCEPTED"):
            used += a["party_size"]
    return used


def _remaining_slots(permit_id: str) -> int:
    store = get_store()
    permit = store.lottery_permits[permit_id]
    return permit["daily_slot_count"] - _awarded_slots_used(permit_id)


def run_draw(permit_id: str) -> dict:
    """Run the waterfall allocation. Caller must have already validated park frozen/state."""
    store = get_store()
    permit = store.lottery_permits[permit_id]

    eligible = []
    for a in store.lottery_applications.values():
        if a["lottery_permit_id"] != permit_id:
            continue
        if a["status"] != "SUBMITTED":
            continue
        visitor = store.visitors.get(a["visitor_id"])
        if visitor is None:
            continue
        if visitor.get("lottery_strikes", 0) >= MAX_STRIKES:
            continue
        eligible.append(a)
    eligible.sort(key=lambda a: (a["rank_seed"], a["created_at"]))

    remaining = permit["daily_slot_count"]
    draw_at_dt = parse_iso8601(permit["draw_at"])
    award_expiry = None
    if draw_at_dt is not None:
        award_expiry = format_iso8601(draw_at_dt + timedelta(hours=AWARD_EXPIRY_HOURS))

    for app in eligible:
        if remaining >= app["party_size"]:
            app["status"] = "AWARDED"
            app["award_expires_at"] = award_expiry
            remaining -= app["party_size"]
            stamp_update(app)
        else:
            app["status"] = "WAITLISTED"
            stamp_update(app)

    permit["status"] = "DRAWN"
    stamp_update(permit)
    return permit


def promote_next_waitlisted(permit_id: str) -> Optional[dict]:
    """Find the next WAITLISTED app with capacity, promote to AWARDED."""
    store = get_store()
    permit = store.lottery_permits[permit_id]
    remaining = _remaining_slots(permit_id)
    if remaining <= 0:
        return None
    candidates = [
        a for a in store.lottery_applications.values()
        if a["lottery_permit_id"] == permit_id and a["status"] == "WAITLISTED"
    ]
    candidates.sort(key=lambda a: (a["rank_seed"], a["created_at"]))
    draw_at_dt = parse_iso8601(permit["draw_at"])
    award_expiry = None
    if draw_at_dt is not None:
        award_expiry = format_iso8601(draw_at_dt + timedelta(hours=AWARD_EXPIRY_HOURS))
    for app in candidates:
        if app["party_size"] <= remaining:
            app["status"] = "AWARDED"
            app["award_expires_at"] = award_expiry
            stamp_update(app)
            return app
    return None
