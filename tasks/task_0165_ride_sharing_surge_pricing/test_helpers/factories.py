"""Payload factories — one per entity, input fields only.

The factories below emit ONLY the source: input fields the PRD declares
on each entity. Timestamp helpers render ISO 8601 UTC with three
fractional digits per PRD §2.4 ("an ISO 8601 UTC timestamp with three
fractional digits").
"""
from __future__ import annotations

import random
import string
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Random / unique helpers
# ---------------------------------------------------------------------------
_grid_lock = threading.Lock()
_grid_counter = 0


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def next_grid_code() -> str:
    """Allocate a fresh G-NNN code that satisfies PRD §3.1 regex
    ^G-[0-9]{3}$ and is globally unique within the process.

    Counter is shared across tests; mod 1000 keeps it inside the 3-digit
    range. Bench runners reset state between tests so collisions inside
    the implementation are not a concern; this helper just guards
    against same-test collisions when many grids are needed.
    """
    global _grid_counter
    with _grid_lock:
        _grid_counter = (_grid_counter + 1) % 1000
        return f"G-{_grid_counter:03d}"


def grid_code_with_numeric(n: int) -> str:
    """Build the G-NNN code for a specific numeric portion in [0,999]."""
    assert 0 <= n <= 999
    return f"G-{n:03d}"


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 demands ISO 8601 UTC with 3 fractional digits.
# ---------------------------------------------------------------------------
def iso_now_utc() -> str:
    return iso_from_dt(datetime.now(timezone.utc))


def iso_from_dt(dt: datetime) -> str:
    """Render dt as ISO 8601 UTC with three fractional digits and a Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return f"{base}.{millis:03d}Z"


def add_seconds_iso(iso: str, seconds: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(seconds=seconds))


def add_minutes_iso(iso: str, minutes: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(minutes=minutes))


def add_hours_iso(iso: str, hours: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(hours=hours))


def add_days_iso(iso: str, days: int) -> str:
    return iso_from_dt(_parse_iso(iso) + timedelta(days=days))


def _parse_iso(iso: str) -> datetime:
    s = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def day_of_week_from_iso(iso: str) -> str:
    """Return the PRD-spelled day-of-week (MON..SUN) for the given UTC
    timestamp. PRD §3.5 enumerates exactly these strings.
    """
    dt = _parse_iso(iso).astimezone(timezone.utc)
    return ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")[dt.weekday()]


def minute_of_day_from_iso(iso: str) -> int:
    """Return minute_of_day in UTC (0..1439)."""
    dt = _parse_iso(iso).astimezone(timezone.utc)
    return dt.hour * 60 + dt.minute


# ---------------------------------------------------------------------------
# Grid / Driver / Rider payloads — PRD §3.1, §3.2, §3.3.
# ---------------------------------------------------------------------------
def create_grid_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: a grid is created with code (regex ^G-[0-9]{3}$),
    name; optional is_airport (default false), rush_hour_eligible
    (default true)."""
    payload: Dict[str, Any] = {
        "code": next_grid_code(),
        "name": f"Grid-{random_suffix(6)}",
    }
    payload.update(overrides)
    return payload


def patch_grid_payload(*, version: int, **overrides) -> Dict[str, Any]:
    """PRD §2.7: PATCH carries an optional version field; we always
    include it so the OCC pathway is exercised."""
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def create_driver_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2: a driver is created with just a name."""
    payload = {"name": f"Driver-{random_suffix(6)}"}
    payload.update(overrides)
    return payload


def create_rider_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3: a rider is created with just a name."""
    payload = {"name": f"Rider-{random_suffix(6)}"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RushHourWindow payloads — PRD §3.5.
# ---------------------------------------------------------------------------
def create_rush_hour_window_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "label": f"Window-{random_suffix(6)}",
        "day_of_week": "MON",
        "start_minute": 480,         # 08:00 UTC
        "end_minute": 540,           # 09:00 UTC
        "additive_bonus": 0.50,
    }
    payload.update(overrides)
    return payload


def patch_rush_hour_window_payload(*, version: int,
                                   **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# QuestBonus payloads — PRD §3.6.
# ---------------------------------------------------------------------------
def create_quest_bonus_payload(window_start: Optional[str] = None,
                               window_end: Optional[str] = None,
                               **overrides) -> Dict[str, Any]:
    if window_start is None:
        window_start = iso_now_utc()
    if window_end is None:
        window_end = add_hours_iso(window_start, 1)
    payload: Dict[str, Any] = {
        "name": f"Quest-{random_suffix(6)}",
        "target_ride_count": 2,
        "bonus_amount_cents": 5_000,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def patch_driver_quest_payload(quest_id: Optional[str],
                               *, version: int) -> Dict[str, Any]:
    """PRD §3.6: body provides quest_id (or null to unenroll); PRD §2.7
    OCC: include version."""
    return {"quest_id": quest_id, "version": version}


# ---------------------------------------------------------------------------
# Ride / Dispute payloads — PRD §3.3, §3.7.
# ---------------------------------------------------------------------------
def create_ride_payload(pickup_grid_code: str,
                        dropoff_grid_code: Optional[str] = None,
                        distance_km: float = 5.0,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "pickup_grid_code": pickup_grid_code,
        "dropoff_grid_code": dropoff_grid_code or pickup_grid_code,
        "distance_km": distance_km,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(ride_id: str,
                           requested_refund_cents: int,
                           reason_code: str = "OVERCHARGE",
                           **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ride_id": ride_id,
        "reason_code": reason_code,
        "requested_refund_cents": requested_refund_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Driver lifecycle payloads — PRD §3.2.
# ---------------------------------------------------------------------------
def go_online_payload(grid_code: str) -> Dict[str, Any]:
    return {"grid_code": grid_code}


def airport_queue_join_payload(grid_code: str) -> Dict[str, Any]:
    return {"grid_code": grid_code}


# ---------------------------------------------------------------------------
# Test-driving endpoints.
# ---------------------------------------------------------------------------
def clock_advance_payload(target_timestamp: str) -> Dict[str, Any]:
    return {"target_timestamp": target_timestamp}


__all__ = [
    "add_days_iso",
    "add_hours_iso",
    "add_minutes_iso",
    "add_seconds_iso",
    "airport_queue_join_payload",
    "clock_advance_payload",
    "create_dispute_payload",
    "create_driver_payload",
    "create_grid_payload",
    "create_quest_bonus_payload",
    "create_ride_payload",
    "create_rider_payload",
    "create_rush_hour_window_payload",
    "day_of_week_from_iso",
    "go_online_payload",
    "grid_code_with_numeric",
    "iso_from_dt",
    "iso_now_utc",
    "minute_of_day_from_iso",
    "next_grid_code",
    "patch_driver_quest_payload",
    "patch_grid_payload",
    "patch_rush_hour_window_payload",
    "random_suffix",
]
