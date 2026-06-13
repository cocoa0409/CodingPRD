"""In-memory data store. Starts EMPTY on every boot; no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.venues = {}
        self.spaces = {}
        self.packages = {}
        self.clients = {}
        self.coordinators = {}
        self.bookings = {}
        self.space_holds = {}
        self.milestones = {}
        self.payments = {}
        self.vendors = {}
        self.guarantees = {}
        self.walkthroughs = {}
        self.reschedule_requests = {}

        # monotonic counter giving each record a stable creation order
        self._seq = 0

        # simulated current clock (drives all temporal checks). Defaults to the
        # real wall clock; tests override via POST /_clock/set.
        self.clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


store = Store()
