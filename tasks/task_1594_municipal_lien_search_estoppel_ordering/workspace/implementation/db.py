"""In-memory data store + logical clock.

The store starts empty on every boot. The logical clock starts at exactly
2026-08-01T00:00:00Z and is only advanced via POST /_clock/set_current_utc.
The server never consults wall-clock time.
"""
import itertools
import uuid
from datetime import datetime, timezone

START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {
    "clock": START_CLOCK,
    "seq": itertools.count(1),
}

# Entity stores: id -> dict
jurisdictions = {}
statutes = {}
departments = {}
associations = {}
search_orders = {}
research_tasks = {}
estoppel_orders = {}
discrepancies = {}
deliveries = {}


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def today():
    return _state["clock"].date()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(now())


def stamp(entity):
    """Initialize common fields on a freshly created entity."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next(_state["seq"])
    entity["_created_date"] = today()


def touch(entity):
    """Record one accepted mutation: version +1, updated_at refreshed."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1
