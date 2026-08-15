"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.technicians = {}
        self.units = {}
        self.vendors = {}
        self.rotation_shifts = {}
        self.call_tickets = {}
        self.work_orders = {}
        self.vendor_authorizations = {}
        self.relocation_cases = {}
        self.incident_records = {}
        self.pay_periods = {}
        self.pay_statements = {}
        # insertion order counters per collection (created_at ties broken by
        # insertion sequence)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _CLOCK_START

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
