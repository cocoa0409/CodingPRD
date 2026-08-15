"""In-memory data store. Starts empty on every boot — no seeding whatsoever."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.disruption_events = {}
        self.flights = {}
        self.cabin_inventories = {}
        self.passengers = {}
        self.bookings = {}
        self.booking_segments = {}
        self.reaccommodation_cases = {}
        self.reaccommodation_options = {}
        self.interline_agreements = {}
        self.vouchers = {}
        self.crew_assignments = {}
        self.refund_elections = {}
        self.cost_entries = {}
        self.communication_logs = {}
        # Logical clock: server starts at 2026-08-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical time."""
    return db.clock


def iso(dt):
    """Render a datetime as ISO-8601 UTC with exactly three fractional digits.

    If the value is on a whole second, emit ...T00:00:00.000Z style anyway so
    every system-assigned timestamp carries the 3-fractional-digit format.
    """
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return "%s.%03dZ" % (s, ms)
