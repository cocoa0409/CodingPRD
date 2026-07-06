"""In-memory data store. Wiped on every process boot — no seeding, no persistence.

Storage is plain Python dicts keyed by UUID string. Re-invocation of start.sh
starts a fresh process with empty stores.
"""
import uuid
from datetime import datetime, timezone


# --- Logical clock (PRD §2.10) ----------------------------------------------
# Default at startup is exactly 2026-03-01T00:00:00Z and never falls back to
# wall-clock time until explicitly set.
_DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO 8601 UTC instant into an aware datetime (UTC)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    def __init__(self):
        self._dt = _parse_iso(_DEFAULT_CLOCK_ISO)

    def set_from_iso(self, value):
        self._dt = _parse_iso(value)
        return self.current()

    def current(self):
        return self._dt

    def current_iso(self):
        dt = self._dt
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    def epoch_seconds(self):
        return int(self._dt.timestamp())

    def minute_of_day(self):
        return self._dt.hour * 60 + self._dt.minute


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.service_plans = {}
        self.accounts = {}
        self.call_scripts = {}
        self.spam_rules = {}
        self.receptionists = {}
        self.availability_windows = {}
        self.calendar_slots = {}
        self.calls = {}
        self.messages = {}
        self.escalations = {}
        self.crm_handoffs = {}
        self.appointments = {}
        self.billing_periods = {}
        self.clock = Clock()
        # Monotonic counter to break created_at ties deterministically by
        # insertion order (created_at has ms precision; rapid creates can share
        # a timestamp, so we keep a strictly-increasing sequence too).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock ISO timestamp for created_at/updated_at (PRD §2.4).

    These are server-minted record timestamps (audit), distinct from the
    logical clock that drives domain time.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
