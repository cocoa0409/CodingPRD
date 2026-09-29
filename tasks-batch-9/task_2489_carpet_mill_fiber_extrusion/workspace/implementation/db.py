"""In-memory data store.

Everything lives in plain Python dicts keyed by the record's ``id``.  The store
starts completely empty on every boot: no entity is seeded, preloaded or
hardcoded.  Tests build all state through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.10 — the logical clock's startup value.
CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store(object):
    TABLES = (
        "accounts",
        "polymer_lots",
        "reclamation_batches",
        "fiber_batches",
        "styles",
        "machines",
        "vessels",
        "runs",
        "dye_lots",
        "roll_goods",
        "product_tests",
        "certifications",
        "cut_orders",
        "cut_allocations",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.TABLES:
            setattr(self, name, {})
        self.clock_dt = CLOCK_DEFAULT_DT
        self.clock_raw = CLOCK_DEFAULT_RAW
        self._seq = itertools.count(1)
        self._last_dt = None

    # ---- identity / time -------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def now_dt(self):
        """Strictly monotonic wall clock so created_at is always distinct."""
        t = datetime.now(timezone.utc)
        if self._last_dt is not None and t <= self._last_dt:
            t = self._last_dt + timedelta(milliseconds=1)
        self._last_dt = t
        return t

    def now_iso(self):
        return fmt_ts(self.now_dt())


store = Store()


def _touched_set():
    try:
        from flask import g, has_request_context
    except Exception:  # pragma: no cover
        return None
    if not has_request_context():
        return None
    s = getattr(g, "touched_ids", None)
    if s is None:
        s = set()
        g.touched_ids = s
    return s


def insert(table, data, versioned=True):
    """Create a record with the system-managed common fields."""
    rec = dict(data)
    rec["id"] = store.new_id()
    rec["created_at"] = store.now_iso()
    rec["_seq"] = store.next_seq()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    table[rec["id"]] = rec
    s = _touched_set()
    if s is not None:
        # A record created by this request keeps version 1 no matter how many
        # recomputation passes subsequently touch it.
        s.add(rec["id"])
    return rec


def touch(rec):
    """Bump ``version`` by exactly one for this request and restamp updated_at."""
    if "version" not in rec:
        return rec
    s = _touched_set()
    if s is not None:
        if rec["id"] in s:
            return rec
        s.add(rec["id"])
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = store.now_iso()
    return rec


def ordered(records):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
