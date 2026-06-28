"""In-memory data store and the logical clock (PRD Section 2.4).

Storage is in-memory ONLY. Every collection is a plain dict keyed by id.
Nothing is seeded, preloaded, or hardcoded at startup; the store begins empty
on every process boot and tests build all state via the API.
"""
import datetime
import itertools
import uuid


# Logical clock default on server startup (PRD Section 2.4):
# "On server startup the clock reads exactly 2026-01-01T00:00:00Z, and until
#  it is explicitly moved it stays at that default rather than tracking real
#  wall-clock time."
CLOCK_DEFAULT = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


class Store:
    """Holds every entity collection and the logical clock for one process."""

    def __init__(self):
        # One dict per entity type, keyed by id (uuid string).
        self.suppliers = {}
        self.parts = {}
        self.part_revisions = {}
        self.bom_lines = {}
        self.change_requests = {}
        self.change_orders = {}
        self.approval_tasks = {}
        self.affected_items = {}
        self.documents = {}
        self.deviations = {}
        self.supplier_change_notices = {}
        self.serialized_units = {}

        # Logical clock — single instant used for every time-based decision.
        self.clock = CLOCK_DEFAULT

        # Monotonic sequence so created_at ties remain in true insertion order.
        # created_at is an ISO timestamp; this counter guarantees a stable,
        # observable per-line / per-unit ordering even when two rows are minted
        # in the same millisecond (used for BOM-line rollup order, deviation
        # candidate selection, etc., all of which order by created_at ASC).
        self._seq = itertools.count(1)

    # --- timestamps & ids -----------------------------------------------------
    def new_id(self):
        # id is a UUID with no type prefix (PRD Section 2.4).
        return str(uuid.uuid4())

    def now_iso(self):
        """created_at / updated_at: ISO 8601 UTC with three fractional digits."""
        now = datetime.datetime.now(datetime.timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def next_seq(self):
        return next(self._seq)


# Single global store instance, created fresh on every import / process boot.
store = Store()
