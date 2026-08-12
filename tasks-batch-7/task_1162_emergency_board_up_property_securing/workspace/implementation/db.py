"""In-memory data store. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone, timedelta

# --- Logical clock ---
# Startup default is exactly 2026-05-01T00:00:00Z; must NOT fall back to wall clock.
_CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _CLOCK_START

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime):
        self._now = dt


clock = LogicalClock()


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now() -> str:
    return format_ts(clock.now())


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_ts(s: str) -> datetime:
    """Parse an ISO 8601 timestamp (accept trailing Z or offset)."""
    if s is None:
        raise ValueError("missing timestamp")
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- Stores (dicts keyed by id). Entity collections ---
markets = {}
subcontractors = {}
coverages = {}
customers = {}
properties = {}
jobs = {}
assignments = {}
safety_assessments = {}
scope_items = {}
temporary_services = {}
patrol_visits = {}
permit_cases = {}
document_packages = {}
invoices = {}
