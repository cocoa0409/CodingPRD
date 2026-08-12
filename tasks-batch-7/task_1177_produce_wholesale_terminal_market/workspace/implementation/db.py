"""In-memory data store for the Produce Terminal Market API.

The store starts empty on every boot -- no seeding. All timestamps come from
the logical clock (default 2026-05-01T00:00:00Z), never the wall clock.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # entity tables, keyed by id
        self.shippers = {}
        self.customers = {}
        self.commodities = {}
        self.daily_prices = {}
        self.purchase_lots = {}
        self.inspections = {}
        self.temperature_readings = {}
        self.ripening_rooms = {}
        self.ripening_bookings = {}
        self.shrink_records = {}
        self.credit_memos = {}
        self.sales_orders = {}
        self.invoices = {}
        self.payments = {}
        self.labor_tickets = {}
        # logical clock: exactly 2026-05-01T00:00:00Z at boot
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical-clock timestamp, ISO 8601 UTC with three fractional digits."""
    dt = store.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    return store.clock
