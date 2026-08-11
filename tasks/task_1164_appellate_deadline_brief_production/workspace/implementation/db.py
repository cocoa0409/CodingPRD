"""In-memory data store. Starts completely empty on every boot.

Logical clock: pinned at 2026-05-01T00:00:00Z per PRD §2.5.
All timestamps are stored as ISO 8601 UTC strings with three fractional digits.
"""
import threading
import uuid
from datetime import datetime, timezone


_LOCK = threading.RLock()

# Logical clock state
_CLOCK_ISO = "2026-05-01T00:00:00.000Z"


def _now_wall():
    return datetime.now(timezone.utc)


def now_iso():
    """Return the current logical-clock instant as ISO8601 with ms precision."""
    with _LOCK:
        return _CLOCK_ISO


def set_clock(iso_str):
    global _CLOCK_ISO
    with _LOCK:
        _CLOCK_ISO = iso_str


def wall_now_iso():
    """Wall-clock timestamp for api_request_timestamp / created_at bookkeeping."""
    dt = _now_wall()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO8601 string (with optional Z) into an aware datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_iso(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def new_confirmation_number():
    return "CNF-" + uuid.uuid4().hex[:12].upper()


class Store:
    """In-memory entity store. All dicts keyed by id."""

    def __init__(self):
        self.courts = {}
        self.attorneys = {}
        self.cases = {}
        self.events = {}
        self.deadlines = {}
        self.records = {}
        self.transcript_orders = {}
        self.briefing_schedules = {}
        self.briefs = {}
        self.toas = {}
        self.citations = {}
        self.extension_motions = {}
        self.filings = {}
        self.oral_arguments = {}
        self.decisions = {}
        self.petitions = {}
        # creation-order counters for deterministic list sorting
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


STORE = Store()
