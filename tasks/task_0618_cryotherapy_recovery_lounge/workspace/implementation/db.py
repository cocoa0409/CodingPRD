"""In-memory data store (PRD §2.4).

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
All records are plain dicts keyed by their server-minted id.
"""

import itertools
import uuid

from clock import clock, format_iso8601_ms


class Store:
    def __init__(self):
        self.locations = {}
        self.service_types = {}
        self.rooms = {}
        self.technicians = {}
        self.technician_shifts = {}
        self.membership_plans = {}
        self.members = {}
        self.waivers = {}
        self.subscriptions = {}
        self.credit_packs = {}
        self.bookings = {}
        self.invoices = {}
        # Monotonic sequence to give a stable insertion-order tie-break that is
        # independent of timestamp collisions under a frozen logical clock.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def reset(self):
        self.__init__()


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation timestamps are stamped from the logical clock (PRD §2.4)."""
    return format_iso8601_ms(clock.now())
