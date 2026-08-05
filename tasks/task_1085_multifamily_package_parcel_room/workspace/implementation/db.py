"""In-memory data store and logical clock.

Everything lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot; no entity is seeded/preloaded. The logical clock starts at
2026-05-01T00:00:00Z and only ever advances when an operator sets it.
"""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Entity stores
# ---------------------------------------------------------------------------
properties = {}
locker_banks = {}
lockers = {}
shelves = {}
residents = {}
carriers = {}
packages = {}
notifications = {}
retail_returns = {}
storage_charges = {}

# Monotonic insertion sequence for stable ordering / created_at tie-breaks.
_seq = 0

# Logical clock (UTC aware datetime).
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits and Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string (accepts trailing Z) into a UTC aware datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
