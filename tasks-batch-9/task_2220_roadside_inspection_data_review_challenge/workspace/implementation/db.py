"""In-memory data store, logical clock and timestamp handling.

Storage is process-local dictionaries keyed by id. Nothing is seeded: the store
starts completely empty on every boot and all entity data arrives through the
declared API surface.
"""

import copy
import uuid
from datetime import datetime, timedelta, timezone

from flask import g, has_request_context

from errors import err

UTC = timezone.utc

# PRD 2.4: the logical clock starts at this fixed instant and never falls back
# to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def canon(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class TS(object):
    """A timestamp that remembers the literal text it came in as."""

    __slots__ = ("dt", "raw")

    def __init__(self, dt, raw=None):
        self.dt = dt
        self.raw = raw if raw is not None else canon(dt)

    @staticmethod
    def of(dt):
        return TS(dt)

    def plus_days(self, days):
        return TS(self.dt + timedelta(days=days))

    def __repr__(self):  # pragma: no cover - debugging helper
        return "TS(%s)" % self.raw


def parse_iso(value):
    """Parse an ISO-8601 instant, returning an aware UTC datetime."""
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


def parse_ts(value):
    """Parse an input datetime, preserving the caller's original spelling."""
    return TS(parse_iso(value), value if isinstance(value, str) else None)


COLLECTIONS = (
    "carriers",
    "drivers",
    "violation_codes",
    "thresholds",
    "reports",
    "violations",
    "amendments",
    "challenges",
    "evidence",
    "adjudications",
    "basic_scores",
    "coaching",
    "caps",
    "cap_items",
    "runs",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self.seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def snapshot(self):
        state = {"clock": self.clock, "seq": self.seq}
        for name in COLLECTIONS:
            state[name] = copy.deepcopy(getattr(self, name))
        return state

    def restore(self, state):
        self.clock = state["clock"]
        self.seq = state["seq"]
        for name in COLLECTIONS:
            setattr(self, name, state[name])

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock

    def now_ts(self):
        return TS(self.clock)


store = Store()


def new_id():
    return str(uuid.uuid4())


def touched():
    """Set of record ids already version-bumped during this request."""
    if not has_request_context():
        return set()
    if not hasattr(g, "touched"):
        g.touched = set()
    return g.touched


def touch(rec):
    """Refresh updated_at and bump version, at most once per record per request."""
    if "version" not in rec:
        return rec
    seen = touched()
    if rec["id"] in seen:
        return rec
    seen.add(rec["id"])
    rec["updated_at"] = store.now_ts()
    rec["version"] = rec["version"] + 1
    return rec


def base_record(with_version=True):
    """Common record properties (PRD 2.5)."""
    now = store.now_ts()
    rec = {"id": new_id()}
    rec["_seq"] = store.next_seq()
    rec["created_at"] = now
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    # A record created inside this request must not also be version-bumped by a
    # cascade running later in the same request.
    touched().add(rec["id"])
    return rec


def sort_key(rec):
    return (rec["created_at"].dt, rec["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=sort_key)


def serialize(rec, extra=None):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = value.raw if isinstance(value, TS) else value
    if extra:
        for key, value in extra.items():
            out[key] = value.raw if isinstance(value, TS) else value
    return out


def get_or_404(collection, rec_id, error_id):
    if not isinstance(rec_id, str) or rec_id not in collection:
        raise err(error_id)
    return collection[rec_id]
