import uuid
from datetime import datetime, timezone

# Default logical clock at startup
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """In-memory data store. All state wiped on fresh process boot."""

    def __init__(self):
        self.customers = {}
        self.credit_transactions = {}
        self.comic_series = {}
        self.comic_issues = {}
        self.pull_subscriptions = {}
        self.reservations = {}
        self.pre_orders = {}
        self.back_issues = {}
        self.grading_submissions = {}
        self.events = {}
        self.event_registrations = {}
        self.consignments = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def now_iso(self):
        return fmt_ts(self.clock)

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    # ISO 8601 UTC with three fractional digits, Z suffix
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(s):
    if not isinstance(s, str):
        return None
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db = Store()
