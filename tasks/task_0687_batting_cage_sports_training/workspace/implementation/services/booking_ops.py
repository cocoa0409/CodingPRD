"""Shared booking operations: interval helpers, overlap detection, cancel refund.

The cancel refund path here is invoked both by POST /bookings/{id}/cancel and by
the CRITICAL-maintenance cascade (PRD 3.3, 3.7) so they refund identically.
"""
from datetime import timedelta

from clock import clock, parse_iso
from constants import REFUND_CUTOFF_MIN
from db import db
from services import pricing
from services.derive import touch


def occupied_lane_ids(booking):
    """All lanes a booking occupies: primary lane_id + team_lane_ids."""
    ids = [booking["lane_id"]]
    ids.extend(booking.get("team_lane_ids") or [])
    return ids


def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start,end) overlap: each begins strictly before the other ends."""
    return a_start < b_end and b_start < a_end


def booking_conflicts_on_lane(lane, candidate, exclude_booking_id=None):
    """True if candidate booking's interval + lane buffer collides on `lane` with
    any CONFIRMED/CHECKED_IN booking, or any OPEN maintenance window (PRD 3.5).

    The buffer is an idle gap required AFTER each existing booking before the next
    may start (closed-interval adjacency): we extend each occupied booking's end by
    buffer_minutes when testing overlap, and likewise extend the candidate's end so
    a following booking must respect the candidate's buffer too.
    """
    c_start = parse_iso(candidate["start_utc"])
    c_end = parse_iso(candidate["end_utc"])
    buffer_minutes = lane.get("buffer_minutes", 0) or 0
    buf = timedelta(minutes=buffer_minutes)

    lane_id = lane["id"]
    for other in db.bookings.values():
        if other["id"] == candidate["id"]:
            continue
        if exclude_booking_id and other["id"] == exclude_booking_id:
            continue
        if other["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        if lane_id not in occupied_lane_ids(other):
            continue
        o_start = parse_iso(other["start_utc"])
        o_end = parse_iso(other["end_utc"])
        # Apply the buffer on both sides so adjacent bookings must leave the idle gap.
        if intervals_overlap(c_start, c_end + buf, o_start, o_end + buf):
            return True

    # OPEN maintenance windows on this lane (buffer not applied to maintenance).
    for w in db.maintenance.values():
        if w["lane_id"] != lane_id or w["status"] != "OPEN":
            continue
        w_start = parse_iso(w["start_utc"])
        w_end = parse_iso(w["end_utc"])
        if intervals_overlap(c_start, c_end, w_start, w_end):
            return True
    return False


def interval_overlaps_window(booking, window):
    b_start = parse_iso(booking["start_utc"])
    b_end = parse_iso(booking["end_utc"])
    w_start = parse_iso(window["start_utc"])
    w_end = parse_iso(window["end_utc"])
    return intervals_overlap(b_start, b_end, w_start, w_end)


def apply_cancel_refund(booking, member):
    """Apply the refund side effects of moving a CONFIRMED booking to CANCELLED.

    PRD 3.7:
      - TOKEN: time-sensitive waterfall. minutes_to_start >= 120 -> full refund;
        else forfeit ceil(token_cost * 0.5), refund the remainder.
      - MEMBERSHIP: restore minutes fully (duration * lane_count subtracted back).
    Mutates member (caller is responsible for touch()ing member).
    """
    if booking["pay_mode"] == "TOKEN":
        start = parse_iso(booking["start_utc"])
        minutes_to_start = int((start - clock.now()).total_seconds() // 60)
        full = minutes_to_start >= REFUND_CUTOFF_MIN
        refund = pricing.refund_tokens_full_or_partial(booking["token_cost"], full)
        member["token_balance"] += refund
    elif booking["pay_mode"] == "MEMBERSHIP":
        restore = booking["duration_minutes"] * booking["lane_count"]
        member["monthly_member_minutes_used"] -= restore
        if member["monthly_member_minutes_used"] < 0:
            member["monthly_member_minutes_used"] = 0


def cancel_booking(booking, was_confirmed):
    """Transition a booking to CANCELLED with refund cascade and lane release.

    was_confirmed: whether the booking was CONFIRMED (or CHECKED_IN) prior to
    cancel — only then is a refund applied (REQUESTED was never charged).
    Lane interval is released simply by the status no longer being active.
    """
    member = db.members.get(booking["member_id"])
    if was_confirmed and member is not None:
        apply_cancel_refund(booking, member)
        touch(member)
    booking["status"] = "CANCELLED"
    touch(booking)
