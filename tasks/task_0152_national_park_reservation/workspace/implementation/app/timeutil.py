"""Park-local time conversions using zoneinfo / pytz fallback."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional, Tuple

try:
    from zoneinfo import ZoneInfo  # type: ignore
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

try:
    import pytz  # type: ignore
except Exception:  # pragma: no cover
    pytz = None  # type: ignore

from .util import parse_iso8601


def _tz(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    if pytz is not None:
        try:
            return pytz.timezone(name)
        except Exception:
            pass
    raise ValueError(f"Unknown timezone: {name}")


def to_park_local(dt: datetime, tz_name: str) -> datetime:
    """Convert UTC dt -> tz-aware datetime in park-local zone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz(tz_name))


def park_local_to_utc(year: int, month: int, day: int, hour: int, minute: int, tz_name: str) -> datetime:
    """Build a park-local instant and return its UTC equivalent."""
    tz = _tz(tz_name)
    if pytz is not None and isinstance(tz, getattr(pytz.tzinfo, "BaseTzInfo", type(None))):  # type: ignore
        naive = datetime(year, month, day, hour, minute)
        local = tz.localize(naive)  # type: ignore
    else:
        local = datetime(year, month, day, hour, minute, tzinfo=tz)
    return local.astimezone(timezone.utc)


def parse_date_local(s: str) -> Optional[date]:
    if not isinstance(s, str) or len(s) != 10:
        return None
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_hhmm(s: str) -> Optional[Tuple[int, int]]:
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        return None
    try:
        h = int(s[0:2])
        m = int(s[3:5])
    except Exception:
        return None
    if 0 <= h < 24 and 0 <= m < 60:
        return (h, m)
    return None


def park_local_date_at(dt: datetime, tz_name: str) -> date:
    return to_park_local(dt, tz_name).date()


def date_diff_days(d1: date, d2: date) -> int:
    return (d2 - d1).days


def parse_park_local_datetime(s: str) -> Optional[Tuple[int, int, int, int, int]]:
    """Parse a park-local datetime string (YYYY-MM-DDTHH:MM[:SS]).
    Returns tuple (year, month, day, hour, minute) truncating sub-minute.
    """
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1]
    # Strip timezone offset if present (we treat input as park-local)
    for sign in ("+", "-"):
        idx = s.rfind(sign, 11)  # after the date part
        if idx > 10:
            s = s[:idx]
            break
    s = s.replace("T", " ")
    try:
        if "." in s:
            s = s.split(".")[0]
        # Accept HH:MM or HH:MM:SS
        parts = s.split(" ")
        if len(parts) != 2:
            return None
        d_part, t_part = parts
        y, m, d = (int(x) for x in d_part.split("-"))
        t_pieces = t_part.split(":")
        if len(t_pieces) < 2 or len(t_pieces) > 3:
            return None
        h = int(t_pieces[0])
        mi = int(t_pieces[1])
        return (y, m, d, h, mi)
    except Exception:
        return None
