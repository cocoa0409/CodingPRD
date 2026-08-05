"""In-memory data store and logical clock. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone, timedelta

# Logical clock default per PRD 2.5
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.holders = {}
        self.property_types = {}
        self.state_accounts = {}
        self.owners = {}
        self.recovery_firms = {}
        self.properties = {}
        self.notices = {}
        self.reports = {}
        self.claims = {}
        self.evidence = {}
        self.audit_cases = {}
        self.ledger = {}
        self._seq = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def iso_now(self):
        return iso(self.clock)


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime. Returns None on failure."""
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, n):
    """Advance a datetime by n calendar years, clamping Feb 29 -> Feb 28."""
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:
        return dt.replace(year=dt.year + n, day=28)


def full_calendar_years(start, end):
    """Count of full calendar years between start and end, rounded down.
    Returns 0 if end precedes start."""
    if end < start:
        return 0
    years = end.year - start.year
    anniversary = add_years(start, years)
    if anniversary > end:
        years -= 1
    return years
