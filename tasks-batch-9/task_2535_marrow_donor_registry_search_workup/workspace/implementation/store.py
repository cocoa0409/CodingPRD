"""In-memory data store, the logical UTC clock and row helpers.

Storage is process-local Python dicts keyed by id.  The store starts EMPTY on
every boot: no entity is ever seeded, preloaded or hardcoded here.  Tests build
every precondition through the declared endpoints.
"""

import uuid
from datetime import datetime, timezone, date

# PRD 2.4: before any call has been made the logical clock reads exactly this
# instant, and it never falls back to the host's real time.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "registries",
    "centers",
    "patients",
    "searches",
    "donors",
    "candidates",
    "typing_requests",
    "workup_cases",
    "clearance_items",
    "bookings",
    "windows",
    "shipments",
    "followups",
    "claims",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def today(self):
        return self.clock.astimezone(timezone.utc).date()


db = Store()


def new_row(**fields):
    """A row carrying the four common system-managed properties (PRD 2.5)."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def new_append_only_row(**fields):
    """DonorFollowUp rows are immutable: only id and created_at (PRD 2.5)."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": db.now(),
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


# --------------------------------------------------------------------------
# Mutation bookkeeping.  PRD 2.5: version starts at 1 and increments by one on
# every mutation of the row, including mutations the server performs on its own
# initiative inside a cascade.  A row mutated once by a single request advances
# exactly one version, so the bump is de-duplicated per request.
# --------------------------------------------------------------------------
_touched = set()


def begin_request():
    _touched.clear()


def touch(row):
    if row is None:
        return row
    key = id(row)
    if key in _touched:
        row["updated_at"] = db.now()
        return row
    _touched.add(key)
    row["updated_at"] = db.now()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (stable by write order)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def parse_iso_instant(text):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_iso_date(text):
    """Parse a whole UTC calendar day written as YYYY-MM-DD."""
    if not isinstance(text, str) or len(text.strip()) != 10:
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def fmt_date(value):
    if value is None:
        return None
    return value.isoformat()
