"""In-memory data store. Starts EMPTY on every boot. No seeding."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per entity collection, keyed by id
        self.declarations = {}
        self.inspectors = {}
        self.caseworkers = {}
        self.applicants = {}
        self.assessments = {}
        self.ihp_cases = {}
        self.award_line_items = {}
        self.dob_records = {}
        self.appeals = {}
        self.sba_referrals = {}
        self.disbursements = {}
        self.recoupments = {}
        self.rental_periods = {}
        # monotonic insertion sequence for stable created_at ordering
        self._seq = 0
        # logical clock (None => use real wall clock)
        self.current_utc = None

    def next_seq(self):
        self._seq += 1
        return self._seq


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Return server logical-clock-aware ISO 8601 UTC with 3 fractional digits."""
    dt = STORE.current_utc if STORE.current_utc is not None else datetime.now(timezone.utc)
    return _format_iso(dt)


def _format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    """Current logical UTC instant as an aware datetime."""
    if STORE.current_utc is not None:
        return STORE.current_utc
    return datetime.now(timezone.utc)


def to_iso(dt):
    """Serialize an aware datetime to ISO 8601 UTC with 3 fractional digits."""
    return _format_iso(dt)


def parse_iso(value):
    """Parse a stored ISO 8601 UTC string back into an aware datetime."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
