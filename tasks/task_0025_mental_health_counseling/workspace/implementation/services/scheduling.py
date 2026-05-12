"""Slot scheduling validations: overlap, rest interval, daily cap, weekly cap.

Operates against the in-memory db.availability_slots store.
"""
from datetime import datetime

import db
from clock import parse_iso
from errors import err
from services.calculations import (
    overlaps_half_open,
    gap_minutes,
    split_minutes_by_local_day,
    split_minutes_by_iso_week,
    DAILY_CAP_MIN,
    WEEKLY_CAP_MIN,
)


NON_TERMINAL_FOR_INVARIANTS = {"OPEN", "HELD", "BOOKED"}


def _slots_for_counselor(counselor_id: str, exclude_id: str = None):
    out = []
    for s in db.availability_slots.values():
        if s["counselor_id"] != counselor_id:
            continue
        if s["status"] not in NON_TERMINAL_FOR_INVARIANTS:
            continue
        if exclude_id is not None and s["id"] == exclude_id:
            continue
        out.append(s)
    return out


def check_invariants(*, counselor: dict, start_at: datetime, end_at: datetime,
                     exclude_slot_id: str = None):
    """Run §2.11 invariants. Raises an APIError on first violation."""
    tz_name = counselor["timezone"]
    counselor_id = counselor["id"]

    existing = _slots_for_counselor(counselor_id, exclude_id=exclude_slot_id)

    # 1) Overlap (half-open intersection)
    for s in existing:
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"])
        if overlaps_half_open(start_at, end_at, s_start, s_end):
            raise err("ERR_SLOT_OVERLAP",
                      "Proposed slot overlaps an existing slot")

    # 2) Rest interval
    for s in existing:
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"])
        gap = gap_minutes(s_start, s_end, start_at, end_at)
        if 0 < gap < 15:
            raise err("ERR_REST_INTERVAL",
                      "Proposed slot violates 15-minute rest interval")

    # 3) Daily cap (counselor.timezone calendar day)
    proposed_daily = split_minutes_by_local_day(start_at, end_at, tz_name)
    existing_daily: dict = {}
    for s in existing:
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"])
        for k, v in split_minutes_by_local_day(s_start, s_end, tz_name).items():
            existing_daily[k] = existing_daily.get(k, 0) + v
    for day, prop_min in proposed_daily.items():
        existing_min = existing_daily.get(day, 0)
        if existing_min + prop_min > DAILY_CAP_MIN:
            raise err("ERR_DAILY_CAP_EXCEEDED",
                      "Proposed slot exceeds 8-hour daily cap")

    # 4) Weekly cap (counselor ISO week in counselor.timezone)
    proposed_weekly = split_minutes_by_iso_week(start_at, end_at, tz_name)
    existing_weekly: dict = {}
    for s in existing:
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"])
        for k, v in split_minutes_by_iso_week(s_start, s_end, tz_name).items():
            existing_weekly[k] = existing_weekly.get(k, 0) + v
    for wk, prop_min in proposed_weekly.items():
        existing_min = existing_weekly.get(wk, 0)
        if existing_min + prop_min > WEEKLY_CAP_MIN:
            raise err("ERR_WEEKLY_CAP_EXCEEDED",
                      "Proposed slot exceeds 30-hour weekly cap")
