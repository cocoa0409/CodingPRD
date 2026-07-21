"""In-memory data store, logical clock, id/seq generation, timestamp helpers.

Everything lives in module-level state; the test harness restarts the process
before every test (per-test-server isolation), so state is wiped on every boot.
No seeding is performed at startup.
"""

import uuid
from datetime import datetime, timezone, timedelta

from errors import bad_request

# ---------------------------------------------------------------------------
# Collections: id -> record dict
# ---------------------------------------------------------------------------
policies = {}
travelers = {}
vendors = {}
rates = {}
trips = {}
bookings = {}
group_bookings = {}
credits = {}
invoices = {}
invoice_lines = {}

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6). Startup default 2026-07-01T00:00:00Z; never falls
# back to wall-clock time.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}

_seq_counter = {"n": 0}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raise ERR_INVALID_REQUEST
    if it cannot be parsed."""
    if not isinstance(value, str):
        raise bad_request("Invalid datetime value")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request(f"Invalid datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Record lifecycle helpers
# ---------------------------------------------------------------------------
def stamp_new(record):
    """Attach common server-managed fields to a freshly created record."""
    ts = iso(now())
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Register a mutation: bump version and refresh updated_at."""
    record["version"] += 1
    record["updated_at"] = iso(now())
    return record


def public(record):
    """Return a copy of a record without internal (underscore-prefixed) fields."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def add_days(dt, days):
    return dt + timedelta(days=days)
