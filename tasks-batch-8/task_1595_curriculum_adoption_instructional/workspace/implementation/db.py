"""In-memory data store, logical clock, id/timestamp helpers (PRD §2.4, §2.5).

The store starts empty on every boot — nothing is seeded. All entities are
created through the API. The logical clock boots at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

BOOT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = BOOT_CLOCK
        self.seq = itertools.count(1)  # insertion sequence (stable tiebreaks)
        self.frameworks = {}
        self.cycles = {}
        self.materials = {}
        self.alignments = {}          # key: alignment id; also indexed below
        self.alignment_index = {}     # (material_id, standard_code) -> alignment id
        self.pilots = {}
        self.reviews = {}
        self.quotes = {}
        self.purchase_orders = {}
        self.inventory_lots = {}      # key: material_id (one lot per material)
        self.distribution_orders = {}
        self.supplemental_requests = {}
        self.challenge_cases = {}
        self.votes = {}
        self.ledgers = {}             # key: cycle_id (one ledger per cycle)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(store.seq)


# ---------------------------------------------------------------------------
# Datetime helpers — aware UTC datetimes internally.
# ---------------------------------------------------------------------------


def parse_dt(value):
    """Parse an ISO 8601 datetime string; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if not s:
        raise ValueError("empty datetime")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date string YYYY-MM-DD into a date."""
    if not isinstance(value, str):
        raise ValueError("date must be a string")
    s = value.strip()
    dt = datetime.strptime(s, "%Y-%m-%d")
    return dt.date()


def fmt_dt(dt):
    """ISO 8601 UTC; whole seconds render '...T00:00:00Z', sub-second with
    three fractional digits (matches the PRD §2.2/§2.5 shapes)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_timestamp():
    """api_request_timestamp: server wall clock, three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def now_clock():
    return store.clock


def stamp_new(entity):
    """Attach common system fields (PRD §2.5) to a freshly created entity."""
    entity["created_at"] = store.clock
    entity["updated_at"] = store.clock
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def bump(entity):
    """State-transition mutation: refresh updated_at and increment version
    (PRD §2.9 — every state transition increments version by exactly one)."""
    entity["updated_at"] = store.clock
    entity["version"] = entity.get("version", 1) + 1


def refresh(entity):
    """Non-transition mutation (computed/derived field update): refresh
    updated_at only; version is reserved for state transitions (PRD §2.9)."""
    entity["updated_at"] = store.clock
