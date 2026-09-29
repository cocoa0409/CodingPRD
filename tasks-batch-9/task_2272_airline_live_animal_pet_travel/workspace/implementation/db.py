"""In-memory data store, identity, timestamps and the logical clock.

The store is EMPTY on every boot. Nothing is seeded, preloaded or hardcoded.
"""
import itertools
import uuid
from datetime import datetime, timezone

from flask import g

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO-8601 instant into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    """Canonical instant rendering: no fractional part when it is zero."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Wall-clock server timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.species = {}
        self.breeds = {}
        self.dest_reqs = {}
        self.containers = {}
        self.stations = {}
        self.embargo_rules = {}
        self.legs = {}
        self.reservations = {}
        self.animals = {}
        self.segments = {}
        self.docs = {}
        self.allocations = {}
        self.welfare_checks = {}
        self.incidents = {}
        self.clock = parse_iso(CLOCK_DEFAULT_ISO)
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True):
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp, "_seq": store.next_seq()}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation of a row: refresh updated_at and bump version once
    per request (a row mutated several times inside one request is a single
    mutation of that row)."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


def sorted_rows(table):
    """Rows in created_at ascending order (insertion sequence breaks ties)."""
    return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))
