"""In-memory data store, logical clock, id/timestamp helpers."""
import threading
import uuid
from datetime import datetime, timezone, timedelta

LOCK = threading.RLock()

# Entity stores (empty at boot; never seeded)
experts = {}
cases = {}
engagement_requests = {}
conflict_checks = {}
credential_reviews = {}
engagements = {}
productions = {}
reports = {}
venues = {}
schedules = {}
invoices = {}
evaluations = []  # list (terminal records, append-only)

CLOCK_DEFAULT_RAW = "2026-05-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class _Clock:
    """The single logical clock. Starts at exactly 2026-05-01T00:00:00Z."""

    def __init__(self):
        self.dt = parse_iso(CLOCK_DEFAULT_RAW)
        self.raw = CLOCK_DEFAULT_RAW

    def set(self, raw):
        self.dt = parse_iso(raw)
        self.raw = raw

    def now(self):
        return self.dt

    def now_raw(self):
        return self.raw


clock = _Clock()

_last_ts = None


def wall_now_iso():
    """Strictly monotonic wall-clock UTC timestamp, 3 fractional digits, Z suffix."""
    global _last_ts
    with LOCK:
        now = datetime.now(timezone.utc)
        now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
        if _last_ts is not None and now <= _last_ts:
            now = _last_ts + timedelta(milliseconds=1)
        _last_ts = now
        return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


_seq = 0


def base_record():
    """New common-fields skeleton: id/created_at/updated_at/version."""
    global _seq
    with LOCK:
        _seq += 1
        s = _seq
    ts = wall_now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": s,
    }


def touch(rec):
    """Uniform mutation rule: refresh updated_at, increment version by one."""
    rec["updated_at"] = wall_now_iso()
    rec["version"] += 1
