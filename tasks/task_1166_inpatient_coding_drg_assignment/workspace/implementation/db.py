"""In-memory data store and logical clock. Fresh empty state on every boot."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.accounts = {}
        self.charts = {}
        self.deficiencies = {}
        self.dx_lines = {}
        self.proc_lines = {}
        self.coders = {}
        self.assignments = {}
        self.coded_cases = {}
        self.bills = {}
        self.sweeps = {}
        self.audits = {}
        self.findings = {}
        self.reviews = {}
        self.rebills = {}
        self.insert_seq = 0
        self.clock = DEFAULT_CLOCK


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def set_clock(dt):
    store.clock = dt


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_new(res):
    """Populate the common system fields on a freshly created resource."""
    res["id"] = new_id()
    t = now()
    res["created_at"] = t
    res["updated_at"] = t
    res["version"] = 1
    store.insert_seq += 1
    res["_seq"] = store.insert_seq
    return res


def touch(res):
    """Every mutation bumps version and refreshes updated_at (cascades included)."""
    res["version"] += 1
    res["updated_at"] = now()
    return res


def sort_default(items):
    """List endpoints sort by creation timestamp ascending; _seq breaks ties."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
