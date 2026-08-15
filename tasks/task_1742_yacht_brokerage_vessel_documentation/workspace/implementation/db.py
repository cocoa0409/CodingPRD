"""In-memory data store. Starts completely empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.brokerages = {}
        self.agents = {}
        self.clients = {}
        self.vessels = {}
        self.listings = {}
        self.syndication_events = {}
        self.offers = {}
        self.contingencies = {}
        self.escrow_entries = {}
        self.liens = {}
        self.doc_records = {}
        self.statements = {}
        self.tax_assessments = {}
        self.title_transfers = {}
        self.domain_events = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Wall-clock timestamp for created_at/updated_at rendering."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def utc_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    """Logical clock; default startup reads exactly 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current

    def set(self, dt: datetime):
        self._current = dt

    def iso(self) -> str:
        return render_iso(self._current)


clock = LogicalClock()


def render_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime; returns aware datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_in_month(dt: datetime) -> int:
    if dt.month == 12:
        nxt = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
    first = datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)
    return (nxt - first).days
