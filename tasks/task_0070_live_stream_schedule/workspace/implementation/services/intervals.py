"""Interval / time-slot helper logic."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import clock
import db


def overlap(a_start: datetime, a_end: datetime,
            b_start: datetime, b_end: datetime) -> bool:
    """Half-open [start, end) overlap test. Back-to-back does not overlap."""
    return a_start < b_end and b_start < a_end


def studio_interval_conflict(studio_id: str,
                             starts_at: datetime,
                             ends_at: datetime,
                             *,
                             exclude_application_id: str | None = None) -> bool:
    """Returns True if there is any other application on `studio_id` whose
    review_status is APPROVED or whose operational_status is SCHEDULED/LIVE,
    and whose interval overlaps [starts_at, ends_at).
    """
    for app in db.raw_all("applications"):
        if app.get("studio_id") != studio_id:
            continue
        if exclude_application_id and app.get("id") == exclude_application_id:
            continue
        review = app.get("review_status")
        op = app.get("operational_status")
        if review != "APPROVED" and op not in ("SCHEDULED", "LIVE"):
            continue
        a_start = clock.parse_iso(app["starts_at"])
        a_end = clock.parse_iso(app["ends_at"])
        if overlap(starts_at, ends_at, a_start, a_end):
            return True
    return False


def _slot_covers_minute(slot: dict, instant: datetime) -> bool:
    """Whether the given (recurring or one-off) slot covers the supplied UTC
    instant. The slot's `weekday_mask` is interpreted Mon..Sun as bits 0..6.
    A mask of 0 means the slot is non-recurring — the literal [starts_at,
    ends_at) range is the only window.
    """
    s_start = clock.parse_iso(slot["starts_at"])
    s_end = clock.parse_iso(slot["ends_at"])
    mask = int(slot.get("weekday_mask", 0))
    if mask == 0:
        return s_start <= instant < s_end

    # Recurring — daily by weekday. Project (s_start, s_end) onto the day
    # of `instant` and check if that minute falls within.
    if instant < s_start or instant >= _far_future():
        # Recurrences begin at s_start; treat anything earlier as uncovered.
        if instant < s_start:
            return False
    weekday = instant.weekday()  # 0=Mon..6=Sun
    if not (mask >> weekday) & 1:
        return False
    # Build today's projected window using the time-of-day from s_start/s_end.
    day = instant.astimezone(timezone.utc).date()
    today_start = datetime.combine(
        day, s_start.timetz()).astimezone(timezone.utc)
    today_end_date = day if s_end.timetz() > s_start.timetz() else day
    # If end <= start within a day, treat as 24-hour wraparound — but spec
    # implies starts < ends within a single day's projection, so use plain
    # combine.
    today_end = datetime.combine(day, s_end.timetz()).astimezone(timezone.utc)
    if today_end <= today_start:
        # Wrap to next day
        today_end = today_end + timedelta(days=1)
    return today_start <= instant < today_end


def _far_future() -> datetime:
    return datetime(9999, 12, 31, tzinfo=timezone.utc)


def interval_fully_available(studio_id: str,
                             starts_at: datetime,
                             ends_at: datetime) -> bool:
    """True iff every minute of [starts_at, ends_at) is covered by at least
    one AVAILABLE slot on the studio and intersects no MAINTENANCE slot.
    """
    if ends_at <= starts_at:
        return False
    slots = [s for s in db.raw_all("time_slot_configs")
             if s.get("studio_id") == studio_id]
    available = [s for s in slots if s.get("kind") == "AVAILABLE"]
    maintenance = [s for s in slots if s.get("kind") == "MAINTENANCE"]

    # Check maintenance disjointness first using half-open overlap on the
    # literal slot windows (recurring maintenance is supported by projecting
    # day-by-day across the requested interval).
    for slot in maintenance:
        if _slot_overlaps_interval(slot, starts_at, ends_at):
            return False

    # Every minute of [starts_at, ends_at) must be covered.
    minute = starts_at
    step = timedelta(minutes=1)
    while minute < ends_at:
        if not any(_slot_covers_minute(slot, minute) for slot in available):
            return False
        minute = minute + step
    return True


def _slot_overlaps_interval(slot: dict,
                            starts_at: datetime,
                            ends_at: datetime) -> bool:
    """Does the given slot intersect [starts_at, ends_at)?

    For non-recurring slots the literal range is used. For recurring slots we
    iterate by day across the requested interval and project the slot's
    time-of-day onto each day whose weekday bit is set.
    """
    mask = int(slot.get("weekday_mask", 0))
    s_start = clock.parse_iso(slot["starts_at"])
    s_end = clock.parse_iso(slot["ends_at"])
    if mask == 0:
        return overlap(starts_at, ends_at, s_start, s_end)

    # Walk each day in [starts_at.date()-1, ends_at.date()+1].
    cur = starts_at.astimezone(timezone.utc).date() - timedelta(days=1)
    end_date = ends_at.astimezone(timezone.utc).date() + timedelta(days=1)
    while cur <= end_date:
        weekday = cur.weekday()
        if (mask >> weekday) & 1:
            day_start = datetime.combine(cur, s_start.timetz()).astimezone(timezone.utc)
            day_end = datetime.combine(cur, s_end.timetz()).astimezone(timezone.utc)
            if day_end <= day_start:
                day_end = day_end + timedelta(days=1)
            if day_start >= s_start and overlap(starts_at, ends_at, day_start, day_end):
                return True
        cur = cur + timedelta(days=1)
    return False
