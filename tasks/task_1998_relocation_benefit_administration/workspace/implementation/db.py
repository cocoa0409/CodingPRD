"""In-memory data store. Starts empty on every boot — no seeding."""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections
        self.employees = {}
        self.policies = {}
        self.vendors = {}
        self.cases = {}
        self.move_assignments = {}
        self.service_bookings = {}
        self.expense_claims = {}
        self.home_sales = {}
        self.repayment_agreements = {}
        self.exception_requests = {}
        # insertion order tracking for created_at-asc sort stability
        self._seq = 0
        # logical clock
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.logical_clock

    def set_now(self, dt):
        self.logical_clock = dt


DB = Store()


def iso_ts(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp; supports trailing Z or explicit offset."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
