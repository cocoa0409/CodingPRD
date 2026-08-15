import itertools
import uuid
from datetime import datetime, timezone


class Store:
    """Process-local in-memory store. Starts completely empty on every boot —
    no seeding; tests construct all state through the declared API surface."""

    def __init__(self):
        self.clients = {}
        self.appraisers = {}
        self.engagements = {}
        self.submissions = {}
        self.approaches = {}
        self.comparables = {}
        self.reports = {}
        self.revision_requests = {}
        self.retention_records = {}
        self.seq = itertools.count(1)
        # Logical clock: before any clock-setting call it reads exactly
        # 2026-08-01T00:00:00Z and never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-08-01T00:00:00Z"


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_rec(fields=None):
    rec = {
        "id": new_id(),
        "created_at": store.clock,
        "updated_at": store.clock,
        "version": 1,
        "_seq": next(store.seq),
    }
    if fields:
        rec.update(fields)
    return rec


def touch(rec):
    rec["updated_at"] = store.clock
    rec["version"] += 1


def parse_dt(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z, offsets, date-only)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_years(dt, n):
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + n, day=28)


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out
