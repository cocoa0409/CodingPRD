"""In-memory data store, logical clock and row bookkeeping.

The store is a set of plain dicts and starts COMPLETELY EMPTY on every boot.
Nothing is seeded, preloaded or hardcoded: every entity a test needs is built
through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Collections — keyed by id
# ---------------------------------------------------------------------------
assets = {}
reservations = {}
bids = {}
dispatches = {}
telemetry = {}
safety_events = {}
obligations = {}
capacity_tests = {}
warranty_claims = {}

_lock = threading.RLock()

# Monotonic insertion counter.  created_at is an ISO string at millisecond
# resolution, so two rows inserted inside the same millisecond would tie; the
# sequence gives every ordering ("newest created_at first", "created_at ASC as
# the only permitted tie-break") a total, reproducible order.
_seq = 0

# PRD §2.8 — before it is ever set the logical clock reads exactly this instant
# and never falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = CLOCK_EPOCH


def reset():
    """Wipe every collection (used only by the process bootstrap)."""
    global _seq, _clock
    with _lock:
        for coll in (assets, reservations, bids, dispatches, telemetry,
                     safety_events, obligations, capacity_tests,
                     warranty_claims):
            coll.clear()
        _seq = 0
        _clock = CLOCK_EPOCH


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def hours_between(start, end):
    """Signed elapsed hours between two datetimes as a float."""
    return (end - start).total_seconds() / 3600.0


def days_between(start, end):
    return (end - start).total_seconds() / 86400.0


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _wall_now():
    return datetime.now(timezone.utc)


def next_seq():
    global _seq
    with _lock:
        _seq += 1
        return _seq


def new_row(versioned=True):
    """Common fields (PRD §2.4): id, created_at and — except on telemetry
    samples, which are immutable measurements — updated_at and version."""
    stamp = fmt_dt(_wall_now())
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Refresh updated_at and advance version by exactly one."""
    row["updated_at"] = fmt_dt(_wall_now())
    row["version"] = int(row.get("version", 0)) + 1
    return row


def serialize(row):
    """Public projection: every key that is not internal bookkeeping."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_newest_first(rows):
    return sorted(rows, key=lambda r: r["_seq"], reverse=True)


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: r["_seq"])
