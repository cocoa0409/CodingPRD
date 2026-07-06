"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every process boot — nothing is seeded or preloaded.
Every entity is created by tests via the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone

# Logical clock default (PRD 2.9): exactly 2026-03-01T00:00:00Z at startup.
DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per primary resource type, keyed by id.
        self.clients = {}
        self.shoppers = {}
        self.certification_attempts = {}
        self.locations = {}
        self.scripts = {}
        self.waves = {}
        self.assignments = {}
        self.evidence = {}
        self.scorecards = {}
        self.reimbursements = {}
        self.disputes = {}
        self.payout_batches = {}
        # Monotonic creation sequence to provide a stable created_at ordering
        # even when many rows share the same millisecond timestamp.
        self._seq = 0
        # Logical clock — server-held, starts at the default and never falls
        # back to wall-clock time (PRD 2.9). Set after construction below.
        self.clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    # Server-minted UUID with no type prefix (PRD 2.4).
    return str(uuid.uuid4())


def now_iso_millis(dt=None):
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.4)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_create(record):
    """Attach common system fields at creation (PRD 2.4)."""
    ts = now_iso_millis()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Advance updated_at and version on every mutation (PRD 2.4)."""
    record["updated_at"] = now_iso_millis()
    record["version"] = record.get("version", 1) + 1


# Instantiate the store after all helpers are defined, then seed the logical
# clock with the default (parse_iso is available by now).
db = Store()
db.clock = parse_iso(DEFAULT_CLOCK_ISO)
