"""In-memory data store and logical clock.

Storage is in-memory only (plain dicts keyed by id). Every byte of state is
recreated fresh on process start; nothing is seeded or persisted.
"""
import threading
import uuid
from datetime import datetime, timezone

# PRD §2.7: On startup the clock reads exactly 2026-01-01T00:00:00Z.
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 instant (accepts trailing Z) into an aware datetime."""
    if value is None:
        return None
    s = value
    if isinstance(s, str) and s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    """Server logical clock used for all window/deadline checks."""

    def __init__(self):
        self._dt = _parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso_value):
        self._dt = _parse_iso(iso_value)

    def now(self):
        return self._dt

    def now_iso_ms(self):
        return _format_ms(self._dt)


class Store:
    """All entity tables. Each is a dict keyed by the entity id (UUID string)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # Monotonic creation counter. created_at is stamped from the logical
        # clock (PRD §2.7), which is frozen between set-calls, so two resources
        # created in the same instant share an identical created_at string. This
        # sequence preserves true creation order as a deterministic tiebreaker
        # for "ascending created_at" ordering (PRD §2.3, §3.8) without leaking
        # into any response (serialize() strips underscore-prefixed fields).
        self._seq = 0
        self.programs = {}
        self.employees = {}
        self.charities = {}
        self.campaigns = {}
        self.donations = {}
        self.payroll_schedules = {}
        self.matching_gifts = {}
        self.volunteer_logs = {}
        self.disbursement_batches = {}
        self.grants = {}
        self.tax_statements = {}

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        """Return the next monotonic creation sequence number (1-based)."""
        self._seq += 1
        return self._seq


db = Store()


def new_request_id():
    return "req_" + uuid.uuid4().hex


def parse_iso(value):
    return _parse_iso(value)
