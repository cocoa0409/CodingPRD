"""In-memory data store, logical clock, and shared time helpers."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, has_request_context

UTC = timezone.utc

# PRD 2.5: the logical clock starts at exactly this instant on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "facilities",
    "providers",
    "infants",
    "encounters",
    "episodes",
    "slots",
    "appointments",
    "evaluations",
    "referrals",
    "risk_entries",
    "tasks",
    "periods",
    "reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_START
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical clock instant."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    return fmt_dt(datetime.now(UTC))


def parse_dt(value):
    """Parse an ISO 8601 instant. Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def add_days(dt, days):
    return dt + timedelta(seconds=86400 * days)


def add_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def floor_days(later, earlier):
    """floor((later - earlier) / 86400 seconds)."""
    return int((later - earlier).total_seconds() // 86400)


def sort_rows(rows):
    """Default ordering: created_at ascending, insertion sequence as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def latest(rows):
    """Row with the greatest created_at (insertion sequence as tiebreak)."""
    ordered = sort_rows(rows)
    return ordered[-1] if ordered else None


def base_row(with_version=True):
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": store.next_seq(),
    }
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    _fresh_list().append(row)
    return row


def _fresh_list():
    """Rows created by the current request never take a version bump."""
    if has_request_context():
        return g.setdefault("_fresh_rows", [])
    if not hasattr(store, "_fallback_fresh"):
        store._fallback_fresh = []
    return store._fallback_fresh


def _dirty_list():
    if has_request_context():
        return g.setdefault("_dirty_rows", [])
    if not hasattr(store, "_fallback_dirty"):
        store._fallback_dirty = []
    return store._fallback_dirty


def touch(row):
    """Mark a versioned row as mutated by this request (at most one bump)."""
    if row is None or "version" not in row:
        return
    for fresh in _fresh_list():
        if fresh is row:
            return
    rows = _dirty_list()
    for existing in rows:
        if existing is row:
            return
    rows.append(row)


def flush_dirty():
    """Apply the pending version/updated_at bumps exactly once per row."""
    rows = _dirty_list()
    if not rows:
        return
    stamp = now()
    for row in rows:
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = stamp
    del rows[:]
