"""Logical server clock + ISO 8601 helpers."""
from datetime import datetime, timezone, date, timedelta


# Server's authoritative wall clock; advances monotonically via POST /_clock/advance.
# PRD §2.12 does not pin an initial value; choose a deterministic early epoch so the
# test-driving capability (POST /_clock/advance) can monotonically reach any of the
# 2026/2027/2028 timestamps the test scenarios use without colliding with wall time.
_logical_now: datetime = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    return _logical_now


def now_iso() -> str:
    return iso(_logical_now)


def set_now(dt: datetime) -> None:
    global _logical_now
    _logical_now = dt


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_date(d) -> str:
    """ISO date for date-only fields, return as ISO 8601 with .000Z suffix at midnight UTC."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return iso(d)
    if isinstance(d, date):
        dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        return iso(dt)
    return d


def parse_iso(s: str) -> datetime:
    if s is None:
        raise ValueError("timestamp is None")
    if not isinstance(s, str):
        raise ValueError("timestamp not a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as e:
        raise ValueError(f"invalid ISO 8601: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_iso_date(s: str) -> date:
    """Accept either a pure date 'YYYY-MM-DD' or a datetime; return UTC date portion."""
    if s is None:
        raise ValueError("date is None")
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc).date()
    if not isinstance(s, str):
        raise ValueError("date not a string")
    raw = s.strip()
    # YYYY-MM-DD shape
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date(int(raw[:4]), int(raw[5:7]), int(raw[8:10]))
        except Exception as e:
            raise ValueError(f"invalid date: {s}") from e
    # else treat as full ISO datetime
    return parse_iso(raw).date()


def date_to_dt_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
