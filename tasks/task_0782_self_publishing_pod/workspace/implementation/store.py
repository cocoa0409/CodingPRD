"""In-memory data store and logical clock.

All state lives in module-level dicts. The store starts EMPTY on every boot —
nothing is seeded, preloaded, or hardcoded. Every entity is created by tests via
the declared API surface.
"""
import uuid
from datetime import datetime, timezone


def now_iso():
    """Real (wall-clock) UTC timestamp, ISO 8601 with exactly 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


CLOCK_DEFAULT_ISO = "2026-03-01T00:00:00Z"


def parse_dt(raw):
    """Parse an ISO-8601 string into an aware UTC datetime. Returns None on failure."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not isinstance(raw, str):
        return None
    s = raw.strip()
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


class Store:
    def __init__(self):
        self.publishers = {}
        self.titles = {}
        self.formats = {}
        self.assets = {}
        self.isbns = {}
        self.channels = {}
        self.prices = {}
        self.proofs = {}
        self.drequests = {}
        self.sales = {}
        self.statements = {}
        self._seq = 0
        self.clock = parse_dt(CLOCK_DEFAULT_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def base_record():
    """Common server-managed fields for a fresh entity."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Mark a record mutated: bump updated_at and version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
