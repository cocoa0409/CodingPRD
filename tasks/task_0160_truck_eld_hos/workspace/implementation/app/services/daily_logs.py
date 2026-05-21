"""DailyLog services: per-day projection of duty events into RODS totals
and the canonical-JSON integrity hash (SCAFFOLD §1.3 daily_log_integrity_hash)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from ..store import store
from ..timeutil import (
    iso_now,
    local_date_str,
    local_midnight_utc,
    next_local_midnight_utc,
    parse_iso,
)


def _round_half_up_6(value: float) -> float:
    d = Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return float(d)


def _events_for_log(log: dict) -> List[dict]:
    return [
        e
        for e in store.duty_events.values()
        if e.get("driver_id") == log["driver_id"]
        and e.get("daily_log_id") == log["id"]
        and e.get("edit_state", "ACTIVE") == "ACTIVE"
    ]


def _canonical_event(e: dict) -> dict:
    """Project an ACTIVE event to its canonical 7-key shape."""
    # Render event_time as ISO 8601 UTC with millisecond precision + trailing Z.
    et = parse_iso(e["event_time"])
    millis = int(et.microsecond / 1000)
    iso = et.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"
    return {
        "event_time": iso,
        "new_status": e["new_status"],
        "vehicle_id": e.get("vehicle_id"),
        "odometer_miles": float(e.get("odometer_miles") or 0),
        "latitude": _round_half_up_6(float(e["latitude"])),
        "longitude": _round_half_up_6(float(e["longitude"])),
        "annotation": e.get("annotation") or "",
    }


def compute_integrity_hash(log: dict) -> str:
    events = _events_for_log(log)
    sorted_events = sorted(events, key=lambda e: (parse_iso(e["event_time"]), e["id"]))
    canonical = json.dumps(
        [_canonical_event(e) for e in sorted_events],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _intervals_clipped_to_log(log: dict) -> List[tuple]:
    """Return (start, end, status) intervals for ACTIVE events belonging to
    this driver, clipped to the log's 24-hour local window."""
    driver = store.drivers[log["driver_id"]]
    tz = driver.get("home_terminal_timezone") or "America/New_York"
    log_start = local_midnight_utc(log["log_date"], tz)
    log_end = next_local_midnight_utc(log["log_date"], tz)

    # All ACTIVE events for the driver (not just those bound to this log id):
    # an event whose time happens to fall on this log's date contributes too.
    # We compute intervals from the full driver event chain and clip.
    all_events = [
        e
        for e in store.duty_events.values()
        if e.get("driver_id") == log["driver_id"]
        and e.get("edit_state", "ACTIVE") == "ACTIVE"
    ]
    all_events.sort(key=lambda e: parse_iso(e["event_time"]))
    intervals = []
    for i, e in enumerate(all_events):
        start = parse_iso(e["event_time"])
        if i + 1 < len(all_events):
            end = parse_iso(all_events[i + 1]["event_time"])
        else:
            end = log_end  # carry the last status to the end of the log
        ovl_s = max(start, log_start)
        ovl_e = min(end, log_end)
        if ovl_e > ovl_s:
            intervals.append((ovl_s, ovl_e, e["new_status"]))
    return intervals


def recompute_log_totals(log: dict) -> None:
    """Recompute total_driving_minutes and total_on_duty_minutes for *log*."""
    intervals = _intervals_clipped_to_log(log)
    driving = 0
    on_duty = 0
    for s, e, status in intervals:
        mins = int((e - s).total_seconds() // 60)
        if status == "DRIVING":
            driving += mins
            on_duty += mins
        elif status in ("ON_DUTY_NOT_DRIVING", "YARD_MOVES"):
            on_duty += mins
    log["total_driving_minutes"] = driving
    log["total_on_duty_minutes"] = on_duty


def find_or_create_daily_log(driver: dict, event_time: datetime) -> dict:
    """Return the DailyLog for the driver on the calendar date implied by
    *event_time* in the driver's home_terminal_timezone, creating it on demand."""
    tz = driver.get("home_terminal_timezone") or "America/New_York"
    date_str = local_date_str(event_time, tz)
    # Lookup existing.
    for log in store.daily_logs.values():
        if log["driver_id"] == driver["id"] and log["log_date"] == date_str:
            return log
    # Create.
    new_log = {
        "driver_id": driver["id"],
        "log_date": date_str,
        "status": "UNCERTIFIED",
        "certified_at": None,
        "certification_count": 0,
        "total_driving_minutes": 0,
        "total_on_duty_minutes": 0,
        "integrity_hash": None,
    }
    store.stamp_create(new_log)
    store.daily_logs[new_log["id"]] = new_log
    return new_log


def recompute_log_full(log: dict) -> None:
    """Bump totals + integrity_hash + version + updated_at on a daily log."""
    recompute_log_totals(log)
    log["integrity_hash"] = compute_integrity_hash(log)
    store.bump(log)
