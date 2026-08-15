import uuid
from datetime import datetime, timezone


class Store:
    """In-memory data store. A fresh Store() exists per process boot; nothing is seeded."""

    def __init__(self):
        self.students = {}
        self.staff = {}
        self.reports = {}
        self.cases = {}
        self.scorings = {}
        self.plans = {}
        self.assessments = {}
        self.leave_decisions = {}
        self.reentries = {}
        self.checkins = {}
        self.grants = {}
        self.trends = {}
        # Logical clock: starts at exactly 2026-08-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0


store = Store()


def now():
    return store.clock


def new_record():
    store.seq += 1
    n = store.clock
    return {
        "id": str(uuid.uuid4()),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": store.seq,
    }


def touch(rec):
    rec["updated_at"] = store.clock
    rec["version"] += 1


def iso_z(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso_z(v)
        else:
            out[k] = v
    return out


def all_sorted(table):
    return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))
