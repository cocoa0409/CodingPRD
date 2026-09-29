"""In-memory data store.  Starts completely EMPTY on every boot -- nothing is
seeded, preloaded or hardcoded.  Every entity is created through the declared
API surface."""

import uuid
from datetime import datetime, timezone

# PRD 2.6 -- the logical clock reads exactly this at startup and never falls
# back to wall-clock time.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.programs = {}
        self.issuers = {}
        self.agreements = {}
        self.orders = {}
        self.members = {}
        self.transactions = {}
        self.campaigns = {}
        self.windows = {}
        self.bookings = {}
        self.partners = {}
        self.notices = {}
        self.cases = {}
        self.postings = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())
