"""In-memory data store and logical clock (PRD §2.4, §2.5).

The store starts completely empty on every boot — no seeding, no preloading.
The logical clock boots at 2026-08-01T00:00:00Z and is repositioned only via
POST /safety/_clock/set_current_utc; it never falls back to wall-clock time.
All timestamps are stored as ISO 8601 UTC strings with three fractional digits.
"""
import threading
import uuid
from datetime import date, datetime, timezone

_LOCK = threading.RLock()
_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_dt():
    """Current logical-clock instant (aware UTC datetime)."""
    with _LOCK:
        return _CLOCK


def set_clock(dt):
    global _CLOCK
    with _LOCK:
        _CLOCK = dt


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_iso(now_dt())


def parse_datetime(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError on unparseable input.
    """
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    t = s.strip()
    if not t:
        raise ValueError("empty datetime")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(s):
    """Parse an ISO YYYY-MM-DD date string. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("date must be a string")
    return date.fromisoformat(s.strip())


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


class Store:
    """In-memory entity store. All dicts keyed by id. Empty at boot."""

    def __init__(self):
        self.companies = {}
        self.establishments = {}
        self.employees = {}
        self.cases = {}
        self.day_entries = {}
        self.investigations = {}
        self.corrective_actions = {}
        self.summaries = {}
        self.hour_logs = {}
        self.severe_reports = {}
        self.inspections = {}
        self.citations = {}
        # deterministic creation-order counter (list sort tiebreak)
        self._seq = 0
        # per-establishment sequence number used in case_number minting
        self._establishment_seq = 0
        # per-establishment case counters: est_id -> int
        self._case_seq = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_establishment_seq(self):
        self._establishment_seq += 1
        return self._establishment_seq

    def next_case_seq(self, establishment_id):
        n = self._case_seq.get(establishment_id, 0) + 1
        self._case_seq[establishment_id] = n
        return n


STORE = Store()
