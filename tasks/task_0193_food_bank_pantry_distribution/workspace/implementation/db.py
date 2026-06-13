"""In-memory data store. Starts EMPTY on every boot. No seeding."""
import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.cold_storage_units = {}
        self.inventory_lots = {}
        self.agencies = {}
        self.allocation_cycles = {}
        self.agency_orders = {}
        self.order_lines = {}
        self.client_households = {}
        self.distribution_events = {}
        # Monotonic counter to provide a stable, deterministic created_at tiebreak
        # ordering (FEFO ties broken by created_at; list sort by created_at asc).
        self._seq = itertools.count(1)
        # Logical "current UTC" clock. Defaults to real wall-clock now; tests
        # advance it via POST /_clock/set_current_utc.
        self.current_utc = datetime.now(timezone.utc)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = DB()


def now_iso():
    """ISO 8601 UTC with three fractional digits."""
    return (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )
