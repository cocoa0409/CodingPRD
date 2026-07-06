"""In-memory data store, logical clock, ID/timestamp helpers."""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta

# Startup default logical clock — never falls back to wall-clock time.
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clients = {}
        self.retainer_ledgers = {}
        self.engagements = {}
        self.assets = {}
        self.scans = {}
        self.findings = {}
        self.alerts = {}
        self.incidents = {}
        self.audits = {}
        self.evidence = {}
        self.reports = {}
        self.audit_log = {}
        # Monotonic insertion sequence for stable created_at ordering ties.
        self._seq = 0
        # Logical clock as a timezone-aware datetime.
        self.clock = parse_iso(DEFAULT_CLOCK)

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(chars) for _ in range(20))


def parse_iso(s):
    """Parse an ISO-8601 string into a tz-aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format a tz-aware datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_clock():
    return db.clock


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


db = Store()
