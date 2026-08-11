"""In-memory data store, logical clock, and timestamp helpers.

All state lives in module-level dicts. Every process boot starts empty:
no seeding, no files, no caches. The per-test-server harness restarts the
process before every test, so each test sees a pristine store.
"""

import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not an ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO-8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def wall_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


class LogicalClock:
    """Server-maintained logical clock; never reads wall-clock time."""

    def __init__(self):
        self.current = parse_dt(DEFAULT_CLOCK_ISO)

    def now_iso(self):
        return fmt_dt(self.current)


clock = LogicalClock()

# ---- entity stores (all start empty; nothing is seeded) ----
events = {}
stations = {}
fixers = {}
skills = {}
shifts = {}
visitors = {}
waivers = {}
items = {}
triage_records = {}
stocks = {}
reservations = {}
outcomes = {}
incidents = {}
donations = {}
reports = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_new(rec, with_version=True):
    """Populate common system fields on a freshly created record."""
    rec["id"] = new_id()
    rec["_seq"] = next_seq()
    rec["created_at"] = clock.now_iso()
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and bump version by exactly 1."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] += 1
