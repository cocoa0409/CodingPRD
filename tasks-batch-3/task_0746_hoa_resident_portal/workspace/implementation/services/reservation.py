"""AmenityReservation validation helpers."""

from datetime import timedelta

import db
from errors import raise_error
from utils import parse_iso


def validate_window(amenity, start_ts_iso, end_ts_iso):
    """Enforce window/blackout rules from PRD §3.6 -> ERR_AMENITY_WINDOW_VIOLATION."""
    start_dt = parse_iso(start_ts_iso)
    end_dt = parse_iso(end_ts_iso)

    if not (start_dt < end_dt):
        raise_error("ERR_AMENITY_WINDOW_VIOLATION", "start_ts must be strictly before end_ts")

    # <= 8 hours (end > start + 8h is rejected)
    if end_dt > start_dt + timedelta(hours=8):
        raise_error("ERR_AMENITY_WINDOW_VIOLATION", "reservation span exceeds 8 hours")

    start_hour = start_dt.hour
    # end hour comparison: the "last reservable hour (1..24, exclusive)" — the end_ts's
    # hour must be <= end_hour. If end_ts is exactly at end_hour:00, that's the boundary
    # (allowed). Simpler: treat end_dt.hour as the hour-of-day; permit end_dt.hour==0
    # (midnight) only if end_hour==24 (i.e., end_dt is 00:00 of next day and end_hour is 24).
    # We normalize: compute an "end_hour_effective" = 24 if end_dt is exactly midnight on
    # the day AFTER start_dt AND spans past midnight; else end_dt.hour + (1 if end_dt.minute>0 or end_dt.second>0 or end_dt.microsecond>0 else 0).
    # Simplest correct check per PRD: start_ts must be in [start_hour, end_hour)-band
    # measured by hour-of-day; end_ts's hour position must be within/at end_hour.
    if start_hour < amenity["reservation_window_start_hour"] or start_hour >= amenity["reservation_window_end_hour"]:
        raise_error("ERR_AMENITY_WINDOW_VIOLATION", "start hour outside amenity window")

    # For end_ts, compute the "effective ending hour". If end_dt has non-zero sub-hour components
    # or its hour > start day, we treat it as strictly past that hour.
    # We measure it as end_dt.hour + (1 if any of minute/second/microsecond > 0 else 0).
    # But we also permit end_dt landing on the same day at end_hour exactly.
    end_hour_effective = end_dt.hour
    if end_dt.minute > 0 or end_dt.second > 0 or end_dt.microsecond > 0:
        end_hour_effective = end_dt.hour + 1
    # If end_dt is on the next calendar day relative to start_dt at exactly 00:00, treat as 24.
    if end_dt.date() != start_dt.date():
        # Only allowed if the amenity's end_hour is 24 and end_dt is start_dt's next day at 00:00.
        # Any other crossing-day case is a window violation.
        if not (amenity["reservation_window_end_hour"] == 24
                and end_dt == start_dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)):
            raise_error("ERR_AMENITY_WINDOW_VIOLATION", "reservation spans multiple days")
        end_hour_effective = 24
    if end_hour_effective > amenity["reservation_window_end_hour"]:
        raise_error("ERR_AMENITY_WINDOW_VIOLATION", "end hour outside amenity window")
    if end_hour_effective <= amenity["reservation_window_start_hour"]:
        # e.g. reservation entirely before the start_hour band
        raise_error("ERR_AMENITY_WINDOW_VIOLATION", "end hour outside amenity window")

    # Blackout dates: no reservation may start on or extend into a blackout date.
    blackout = set(amenity.get("blackout_dates") or [])
    if blackout:
        # The set of dates the reservation touches: from start_dt.date() through the last date
        # covered by the half-open [start, end). If end lands exactly at midnight of some date,
        # that date itself is not included (half-open).
        touched = set()
        d = start_dt.date()
        touched.add(d.isoformat())
        # Walk forward until we pass end_dt (half-open on the right).
        cursor = start_dt
        one_day = timedelta(days=1)
        # We add each date d such that some instant in [start, end) has date == d.
        # Equivalent: while (d+1) < end (i.e., the start-of-next-day is strictly before end),
        # advance and include next day.
        next_day_start = start_dt.replace(hour=0, minute=0, second=0, microsecond=0) + one_day
        while next_day_start < end_dt:
            touched.add(next_day_start.date().isoformat())
            next_day_start = next_day_start + one_day
        for iso in touched:
            if iso in blackout:
                raise_error("ERR_AMENITY_WINDOW_VIOLATION", "reservation lands on a blackout date")


def check_capacity(amenity, candidate_start_ts_iso, candidate_end_ts_iso, guest_count):
    """Runs the interval-merge capacity check. Raises ERR_AMENITY_CAPACITY_EXCEEDED on fail."""
    from services import calc

    cand_start = parse_iso(candidate_start_ts_iso)
    cand_end = parse_iso(candidate_end_ts_iso)
    existing = []
    for r in db.amenity_reservations.values():
        if r["amenity_id"] != amenity["id"]:
            continue
        if r["status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        existing.append((parse_iso(r["start_ts"]), parse_iso(r["end_ts"]), r["guest_count"]))
    ok = calc.amenity_capacity_ok(cand_start, cand_end, guest_count, amenity["capacity"], existing)
    if not ok:
        raise_error("ERR_AMENITY_CAPACITY_EXCEEDED", "amenity capacity would be exceeded")
