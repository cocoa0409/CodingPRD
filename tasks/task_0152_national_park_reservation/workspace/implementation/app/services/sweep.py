"""Deferred-action sweep (POST /_sweep/run)."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from ..clock import now_utc
from ..store import get_store
from ..util import parse_iso8601
from .calculations import date_local_at_hm_utc, date_local_at_midnight_utc
from .common import stamp_update
from .lottery import promote_next_waitlisted
from .waitlist import try_promote_one


def _expire_held_timed_entry() -> None:
    store = get_store()
    now = now_utc()
    for r in list(store.timed_entry_reservations.values()):
        if r["status"] != "HELD":
            continue
        held_until = parse_iso8601(r.get("held_until", ""))
        if held_until is None:
            continue
        if now >= held_until:
            r["status"] = "CANCELLED"
            stamp_update(r)


def _expire_held_campground_reservations() -> None:
    store = get_store()
    now = now_utc()
    for r in list(store.campground_reservations.values()):
        if r["status"] != "HELD":
            continue
        held_until = parse_iso8601(r.get("held_until", ""))
        if held_until is None:
            continue
        if now >= held_until:
            r["status"] = "CANCELLED"
            stamp_update(r)
            # cascade: maybe promote a waitlist entry
            try_promote_one(r["campground_id"], r["site_kind"])


def _expire_held_backcountry_permits() -> None:
    store = get_store()
    now = now_utc()
    for p in list(store.backcountry_permits.values()):
        if p["status"] != "HELD":
            continue
        held_until = parse_iso8601(p.get("held_until", ""))
        if held_until is None:
            continue
        if now >= held_until:
            p["status"] = "CANCELLED"
            stamp_update(p)


def _forfeit_awarded_lottery_applications() -> None:
    store = get_store()
    now = now_utc()
    # Collect affected permits to drive subsequent promotion
    affected_permits = set()
    for a in list(store.lottery_applications.values()):
        if a["status"] != "AWARDED":
            continue
        award_expires = parse_iso8601(a.get("award_expires_at", "") or "")
        if award_expires is None:
            continue
        if now >= award_expires:
            a["status"] = "FORFEITED"
            stamp_update(a)
            visitor = store.visitors.get(a["visitor_id"])
            if visitor is not None:
                visitor["lottery_strikes"] = min(3, visitor.get("lottery_strikes", 0) + 1)
                stamp_update(visitor)
            affected_permits.add(a["lottery_permit_id"])
    for permit_id in affected_permits:
        promote_next_waitlisted(permit_id)


def _advance_confirmed_timed_entry() -> None:
    store = get_store()
    now = now_utc()
    for r in list(store.timed_entry_reservations.values()):
        if r["status"] != "CONFIRMED":
            continue
        park = store.parks.get(r["park_id"])
        if park is None:
            continue
        try:
            end_utc = date_local_at_hm_utc(
                r["entry_date_local"],
                int(r["window_end_local"][:2]),
                int(r["window_end_local"][3:5]),
                park["timezone"],
            )
        except Exception:
            continue
        # NO_SHOW if now > window_end + 60 min
        if now > end_utc + timedelta(minutes=60):
            r["status"] = "NO_SHOW"
            stamp_update(r)


def _advance_confirmed_campground_reservations() -> None:
    store = get_store()
    now = now_utc()
    for r in list(store.campground_reservations.values()):
        if r["status"] != "CONFIRMED":
            continue
        cg = store.campgrounds.get(r["campground_id"])
        if cg is None:
            continue
        park = store.parks.get(cg["park_id"])
        if park is None:
            continue
        try:
            check_in_2300_utc = date_local_at_hm_utc(
                r["check_in_date_local"], 23, 0, park["timezone"]
            )
            check_out_1100_utc = date_local_at_hm_utc(
                r["check_out_date_local"], 11, 0, park["timezone"]
            )
        except Exception:
            continue
        # COMPLETED takes precedence when both apply: COMPLETED when check_out 11:00 has passed
        if now >= check_out_1100_utc:
            r["status"] = "COMPLETED"
            stamp_update(r)
        elif now >= check_in_2300_utc and not r.get("checked_in", False):
            r["status"] = "NO_SHOW"
            stamp_update(r)
            visitor = store.visitors.get(r["visitor_id"])
            if visitor is not None:
                visitor["lottery_strikes"] = min(3, visitor.get("lottery_strikes", 0) + 1)
                stamp_update(visitor)
            try_promote_one(r["campground_id"], r["site_kind"])


def _expire_waitlist_entries() -> None:
    store = get_store()
    now = now_utc()
    for w in list(store.waitlist_entries.values()):
        if w["status"] != "WAITING":
            continue
        cg = store.campgrounds.get(w["campground_id"])
        if cg is None:
            continue
        park = store.parks.get(cg["park_id"])
        if park is None:
            continue
        try:
            expiry_utc = date_local_at_hm_utc(
                w["check_in_date_local"], 18, 0, park["timezone"]
            )
        except Exception:
            continue
        if now >= expiry_utc:
            w["status"] = "EXPIRED"


def _trigger_lottery_draws() -> None:
    """Auto-run draws for permits whose draw_at has passed and status is CLOSED."""
    from .lottery import run_draw
    store = get_store()
    now = now_utc()
    for permit in list(store.lottery_permits.values()):
        # Transition OPEN -> CLOSED when lottery_close_at passed
        if permit["status"] == "OPEN":
            close_at = parse_iso8601(permit.get("lottery_close_at", "") or "")
            if close_at is not None and now >= close_at:
                permit["status"] = "CLOSED"
                stamp_update(permit)
        # Auto-draw when draw_at passed
        if permit["status"] == "CLOSED":
            draw_at = parse_iso8601(permit.get("draw_at", "") or "")
            if draw_at is not None and now >= draw_at:
                park = store.parks.get(permit["park_id"])
                if park is None or park.get("status") == "FROZEN":
                    continue
                run_draw(permit["id"])


def _promote_waitlist_within_window() -> None:
    """Sweep WAITING waitlist entries within waitlist_window_hours."""
    store = get_store()
    # Promote one per (campground, site_kind) eligible bucket per pass.
    seen = set()
    for w in list(store.waitlist_entries.values()):
        if w["status"] != "WAITING":
            continue
        key = (w["campground_id"], w["site_kind"])
        if key in seen:
            continue
        seen.add(key)
        try_promote_one(w["campground_id"], w["site_kind"])


def run_sweep() -> None:
    _expire_held_timed_entry()
    _expire_held_campground_reservations()
    _expire_held_backcountry_permits()
    _trigger_lottery_draws()
    _forfeit_awarded_lottery_applications()
    _advance_confirmed_timed_entry()
    _advance_confirmed_campground_reservations()
    _expire_waitlist_entries()
    _promote_waitlist_within_window()
