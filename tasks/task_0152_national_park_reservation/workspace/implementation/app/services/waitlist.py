"""Waitlist promotion logic (per PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from ..clock import now_utc
from ..store import get_store
from ..timeutil import parse_date_local
from ..util import format_iso8601, new_id
from .calculations import (
    PROMOTION_HOLD_HOURS,
    compute_booking_total,
    date_local_at_midnight_utc,
)
from .common import stamp_create, stamp_update
from .inventory import campground_has_inventory


def _check_out_str(check_in: str, nights: int) -> str:
    d = parse_date_local(check_in)
    if d is None:
        return check_in
    end = d + timedelta(days=nights)
    return end.strftime("%Y-%m-%d")


def _eligible_waitlist_entries(campground_id: str, site_kind: str):
    store = get_store()
    cg = store.campgrounds[campground_id]
    park = store.parks[cg["park_id"]]
    tz_name = park["timezone"]
    now = now_utc()
    waitlist_window_hours = cg.get("waitlist_window_hours", 24)
    entries = []
    for w in store.waitlist_entries.values():
        if w["campground_id"] != campground_id:
            continue
        if w["status"] != "WAITING":
            continue
        if w["site_kind"] != site_kind:
            continue
        try:
            check_in_utc = date_local_at_midnight_utc(w["check_in_date_local"], tz_name)
        except Exception:
            continue
        hours_to_check_in = (check_in_utc - now).total_seconds() / 3600.0
        if hours_to_check_in < 0:
            continue
        if hours_to_check_in > waitlist_window_hours:
            continue
        entries.append(w)
    entries.sort(key=lambda e: (e["priority_score"], e["created_at"]))
    return entries


def try_promote_one(campground_id: str, site_kind: str) -> Optional[dict]:
    """Promote the first eligible WaitlistEntry by creating a HELD CampgroundReservation.
    Returns the new reservation dict or None.
    """
    store = get_store()
    cg = store.campgrounds[campground_id]
    nightly_rate = (
        cg["nightly_standard_fee_cents"]
        if site_kind == "STANDARD"
        else cg["nightly_group_fee_cents"]
    )

    for entry in _eligible_waitlist_entries(campground_id, site_kind):
        check_in = entry["check_in_date_local"]
        nights = entry["nights"]
        check_out = _check_out_str(check_in, nights)
        if not campground_has_inventory(campground_id, site_kind, check_in, check_out):
            continue
        # Compute fees
        totals = compute_booking_total(nightly_rate, nights)
        now = now_utc()
        held_until = now + timedelta(hours=PROMOTION_HOLD_HOURS)
        # Set party_size to the minimum allowed for the kind (1 or 7).
        party_size = 1 if site_kind == "STANDARD" else 7
        reservation = {
            "id": new_id(),
            "campground_id": campground_id,
            "visitor_id": entry["visitor_id"],
            "site_kind": site_kind,
            "party_size": party_size,
            "check_in_date_local": check_in,
            "check_out_date_local": check_out,
            "nights": totals["nights"],
            "nightly_rate_cents": totals["nightly_rate_cents"],
            "total_fee_cents": totals["total_fee_cents"],
            "status": "HELD",
            "held_until": format_iso8601(held_until),
            "refund_cents": 0,
        }
        stamp_create(reservation)
        store.campground_reservations[reservation["id"]] = reservation
        entry["status"] = "PROMOTED"
        entry["promoted_reservation_id"] = reservation["id"]
        return reservation
    return None
