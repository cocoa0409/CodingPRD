"""In-memory data store and the logical clock.

The store is created empty on every process boot.  Nothing is ever seeded,
preloaded or hardcoded here - every entity is built by callers through the
declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.4: the logical clock's value before any caller sets it.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.carriers = {}
        self.bonds = {}
        self.ports = {}
        self.movements = {}
        self.ledger_entries = {}
        self.seal_events = {}
        self.holds = {}
        self.amendments = {}
        self.reports = {}
        self.claims = {}
        self.petitions = {}
        self.sweeps = {}
        self.now = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def new_record(full=True):
    """Mint a record with its common audit fields.

    PRD 2.4: every resource carries `id` (a bare UUID) and `created_at`.
    Append-only witnesses (ledger entries, seal events, compliance sweeps)
    carry only those two; every other resource also carries `updated_at`
    and `version` (starting at 1).
    """
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": db.now,
        "_seq": db.next_seq(),
    }
    if full:
        rec["updated_at"] = db.now
        rec["version"] = 1
    return rec


def touch(rec):
    """A mutation refreshes updated_at and increments version (PRD 2.8)."""
    rec["updated_at"] = db.now
    rec["version"] = rec.get("version", 0) + 1


def order_key(rec):
    """created_at ASC with insertion order as the deterministic tiebreak."""
    return (rec["created_at"], rec["_seq"])
