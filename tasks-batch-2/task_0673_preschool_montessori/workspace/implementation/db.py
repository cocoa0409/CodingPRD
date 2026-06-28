"""In-memory data store + logical clock.

Storage is process-local dicts keyed by id. Nothing is persisted to disk and
NOTHING is seeded at startup — every entity is created by the test via the
declared API surface. Re-launching the process wipes all state.
"""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso_millis


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6). Default before any /_clock/set_current_utc call is
# 2026-04-01T00:00:00Z; it never falls back to wall-clock time.
# ---------------------------------------------------------------------------
class Clock:
    DEFAULT = "2026-04-01T00:00:00Z"

    def __init__(self):
        self._current = parse_iso(self.DEFAULT)

    def set(self, iso_str):
        self._current = parse_iso(iso_str)
        return self._current

    def now(self):
        return self._current

    def now_iso(self):
        return iso_from_dt(self._current)


def parse_iso(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_from_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Data store
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.tiers = {}
        self.classrooms = {}
        self.students = {}
        self.applications = {}
        self.enrollments = {}
        self.payments = {}
        self.refund_requests = {}
        self.staff_assignments = {}
        self.assessment_records = {}
        self.conference_slots = {}
        self.observations = {}
        self.clock = Clock()
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        """Monotonic creation sequence used as a deterministic tiebreaker
        when two records share an identical created_at timestamp."""
        return next(self._seq)

    def clock_now(self):
        return self.clock.now()


db = DB()


def new_common_fields(versioned=True):
    """Common system-managed fields (PRD §2.4).

    Every entity carries id + created_at. All but Observation also carry
    updated_at and version (version begins at 1, increments by 1 on mutation).
    """
    ts = now_iso_millis()
    fields = {
        "id": db.new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if versioned:
        fields["updated_at"] = ts
        fields["version"] = 1
    return fields


def touch(entity):
    """Mutation bookkeeping: refresh updated_at, bump version (PRD §2.4)."""
    entity["updated_at"] = now_iso_millis()
    entity["version"] = entity.get("version", 1) + 1
