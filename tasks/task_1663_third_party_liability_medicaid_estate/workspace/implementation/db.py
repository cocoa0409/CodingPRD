"""In-memory data store and the controllable logical clock (PRD §2.5).

Storage is plain Python dicts keyed by id. The store starts EMPTY on every
boot — no seeding, no preloading. The logical clock reads exactly
2026-08-01T00:00:00Z before any call to the clock endpoint and never falls
back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

# --- Entity tables (keyed by id) --------------------------------------------
MEMBERS = {}
CASES = {}
EXPENSE_CLAIMS = {}
LIENS = {}
SETTLEMENTS = {}
POSTINGS = {}
ESTATE_CASES = {}
WAIVERS = {}
NOTICES = {}

_SEQ = [0]  # insertion counter; stable sort tiebreak for equal created_at


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


# --- Logical clock -----------------------------------------------------------
class LogicalClock:
    """Server-side logical clock. Default: exactly 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt

    def today(self):
        return self._current.date()

    def iso(self):
        return iso_z(self._current)


CLOCK = LogicalClock()


def iso_z(dt):
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso_z(s):
    """Parse the timestamps this server mints (…T HH:MM:SS.mmmZ)."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def now_iso():
    return CLOCK.iso()


def new_entity():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """PRD §2.4: any change refreshes updated_at and increments version."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def pub(entity):
    """Public serialization: strip internal underscore-prefixed fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
