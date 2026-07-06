"""In-memory data store, ID/timestamp helpers, and the logical clock.

All state lives in module-level dicts and is wiped on every process start.
Nothing is seeded at import time — tests build all state via the API.
"""
import uuid
from datetime import datetime, timezone

# Logical clock default per PRD §2.10
CLOCK_DEFAULT_ISO = "2026-03-01T00:00:00Z"


class Store:
    def __init__(self):
        # one dict per entity, keyed by id
        self.clients = {}
        self.ledger_accounts = {}
        self.catchup_projects = {}
        self.monthly_closes = {}
        self.close_tasks = {}
        self.ar_invoices = {}
        self.ap_bills = {}
        self.payroll_runs = {}
        self.payroll_allocations = {}
        self.forecasts = {}
        self.forecast_lines = {}
        self.tax_handoffs = {}
        self.retainer_invoices = {}
        # monotonic counter to break created_at ties deterministically
        self._seq = 0
        # logical clock
        self.clock_iso = CLOCK_DEFAULT_ISO


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock server timestamp for created_at/updated_at, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    store._seq += 1
    return store._seq


def parse_iso(value):
    """Parse an ISO 8601 instant into a timezone-aware datetime."""
    if value is None:
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def clock_now():
    return parse_iso(store.clock_iso)
