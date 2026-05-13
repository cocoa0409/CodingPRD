"""Common utilities — pagination, OCC, time math, half-up rounding, etc."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math

from clock import parse_iso
from errors import err


def half_up(value, places: int) -> Decimal:
    """Round a numeric value half-up to N decimal places, returning a Decimal."""
    q = Decimal(10) ** -places
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def half_up_int(value) -> int:
    """Round half-up to integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def occ_check(row: dict, body: dict) -> None:
    """Optimistic concurrency: if body contains 'version', it must match row.version."""
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        try:
            v = int(body["version"])
        except (TypeError, ValueError):
            raise err("ERR_VERSION_CONFLICT", "version must be an integer")
        if v != int(row.get("version", 0)):
            raise err("ERR_VERSION_CONFLICT", "version does not match current row")


def parse_dt(s, name: str = "timestamp") -> datetime:
    try:
        return parse_iso(s)
    except Exception:
        raise err("ERR_VALIDATION", f"{name} is not a valid ISO 8601 timestamp")


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> Decimal:
    """Compute great-circle distance in km. Round half-up to 4 dp."""
    R = 6371.0088
    phi1 = math.radians(float(a_lat))
    phi2 = math.radians(float(b_lat))
    dphi = math.radians(float(b_lat) - float(a_lat))
    dlam = math.radians(float(b_lon) - float(a_lon))
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    d_km = 2 * R * math.asin(math.sqrt(h))
    return half_up(d_km, 4)


def minutes_to_hhmm(dt: datetime) -> int:
    """Return total minutes since midnight for a UTC datetime (local-time-of-day projection).
    Per PRD §2.10 'local time' is projected from the UTC departure timestamp directly
    (the system uses UTC as its operational timezone).
    """
    return dt.hour * 60 + dt.minute


def time_in_peak_windows(dt: datetime, peak_windows: list) -> bool:
    """Check if the projection of dt's time-of-day falls within any peak window.
    Each window is [HH:MM, HH:MM)."""
    if not peak_windows:
        return False
    mins = dt.hour * 60 + dt.minute
    for w in peak_windows:
        try:
            start = _parse_hhmm(w[0])
            end = _parse_hhmm(w[1])
        except Exception:
            continue
        if start <= mins < end:
            return True
    return False


def _parse_hhmm(s: str) -> int:
    parts = s.split(":")
    if len(parts) != 2:
        raise ValueError("bad HH:MM")
    h = int(parts[0]); m = int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("bad HH:MM range")
    return h * 60 + m


def validate_peak_windows(peak_windows, peak_freq, offpeak_freq) -> None:
    """Validate peak window structural rules and headway constraints.
    Raises ERR_INVALID_FREQUENCY_WINDOWS on violation.
    """
    # Headway constraints
    if not isinstance(peak_freq, int) or not isinstance(offpeak_freq, int):
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "Frequency minutes must be integers")
    if not (5 <= peak_freq <= 60):
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "peak_frequency_minutes must be in [5,60]")
    if not (5 <= offpeak_freq <= 120):
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "offpeak_frequency_minutes must be in [5,120]")
    if peak_freq > offpeak_freq:
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "peak headway must be <= off-peak headway")

    if not isinstance(peak_windows, list):
        raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                  "peak_windows must be a list")
    if len(peak_windows) == 0:
        return  # empty windows are permitted; no overlap to check

    parsed = []
    for w in peak_windows:
        if not isinstance(w, list) or len(w) != 2:
            raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                      "each peak window must be [HH:MM, HH:MM]")
        try:
            start = _parse_hhmm(w[0])
            end = _parse_hhmm(w[1])
        except Exception:
            raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                      "peak window has invalid HH:MM format")
        if start >= end:
            raise err("ERR_INVALID_FREQUENCY_WINDOWS",
                      "peak window start must be < end")
        parsed.append((start, end))

    # Sorted ascending and non-overlapping, gap >= 1 minute between successive windows
    for i in range(len(parsed) - 1):
        a_start, a_end = parsed[i]
        b_start, b_end = parsed[i + 1]
        if b_start <= a_end:
            # touching or overlapping
            if b_start - a_end < 1:
                raise err(
                    "ERR_INVALID_FREQUENCY_WINDOWS",
                    "peak windows must be sorted ascending with >=1 minute gap and non-overlapping",
                )
        if b_start < a_start:
            raise err(
                "ERR_INVALID_FREQUENCY_WINDOWS",
                "peak windows must be sorted ascending",
            )


def intervals_overlap_closed_closed(a_start, a_end, b_start, b_end) -> bool:
    """Closed-closed: any common point is overlap (including touching boundaries)."""
    return not (a_end < b_start or b_end < a_start)


def intervals_overlap_closed_open(a_start, a_end, b_start, b_end) -> bool:
    """Closed-open: touching boundaries count as overlap per PRD driver-rule semantics.
    The PRD §3.4 explicitly states: 'even a touching boundary (one run's end equal to
    another's start) counts as conflict and surfaces as ERR_DRIVER_DOUBLE_BOOKED'.
    So treat <= / >= for boundary comparisons.
    """
    return not (a_end < b_start or b_end < a_start)


def utc_month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


def utc_month_end_exclusive(year: int, month: int) -> datetime:
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(year, month + 1, 1, tzinfo=timezone.utc)
