"""In-memory data store and logical clock.

All storage is in plain Python dicts keyed by id. Nothing is persisted to disk.
Every fresh process boot starts with completely empty collections and the
logical clock reset to its documented startup default.
"""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Entity collections (keyed by id)
# ---------------------------------------------------------------------------

loans = {}
borrowers = {}
properties = {}
cases = {}
listings = {}
suspensions = {}
title_commitments = {}
liens = {}
agreements = {}
appointments = {}
reports = {}
disbursements = {}
waivers = {}
recordings = {}
evictions = {}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 8, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt


clock = LogicalClock()


def now_dt() -> datetime:
    return clock.now()


def today():
    return clock.now().date()


def new_id() -> str:
    return str(uuid.uuid4())


def stamp_new(record: dict) -> None:
    ts = iso_ts(now_dt())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1


def touch(record: dict) -> None:
    record["updated_at"] = iso_ts(now_dt())
    record["version"] = int(record.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def iso_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime. Returns datetime (aware) or None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date(value):
    """Parse an ISO 8601 date (YYYY-MM-DD). Returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
