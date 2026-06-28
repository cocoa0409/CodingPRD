"""No-show events, rolling-window strike decay, suspension (PRD §3.6, calc no_show_strike_score)."""
from datetime import timedelta

from db import store
from util import now_clock, parse_iso
from services.common import make_lean, bump
from services.calc import (
    STRIKE_WINDOW_DAYS, SUSPENSION_THRESHOLD, POINTS_NO_SHOW, POINTS_LATE_CANCEL,
)


def create_no_show_event(member_id, booking_id, event_kind):
    """Create a NoShowEvent, then recompute the member's strike/suspension."""
    points = POINTS_NO_SHOW if event_kind == "NO_SHOW" else POINTS_LATE_CANCEL
    ev = make_lean({
        "member_id": member_id,
        "booking_id": booking_id,
        "event_kind": event_kind,
        "points": points,
        "occurred_utc": store.clock["current_utc"],
    })
    store.no_show_events[ev["id"]] = ev
    recompute_member_strike(member_id)
    return ev


def recompute_member_strike(member_id):
    """Rolling-window sum + threshold suspension flip (PRD §3.6)."""
    member = store.members.get(member_id)
    if member is None:
        return
    window_start = now_clock() - timedelta(days=STRIKE_WINDOW_DAYS)
    score = 0
    for ev in store.no_show_events.values():
        if ev["member_id"] != member_id:
            continue
        occurred = parse_iso(ev["occurred_utc"])
        if occurred >= window_start:
            score += ev["points"]

    prev_score = member.get("strike_score")
    prev_status = member.get("status")
    member["strike_score"] = score
    # threshold: >= SUSPENSION_THRESHOLD -> SUSPENDED; < -> ACTIVE (auto-reinstate).
    new_status = "SUSPENDED" if score >= SUSPENSION_THRESHOLD else "ACTIVE"
    member["status"] = new_status
    if prev_score != score or prev_status != new_status:
        bump(member)
