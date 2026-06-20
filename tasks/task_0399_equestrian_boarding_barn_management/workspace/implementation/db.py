"""In-memory data store. All state lives in process memory keyed by id.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or hardcoded
at startup — every entity any test needs is constructed by the test via the
declared API surface. The per-test-server isolation re-invokes start.sh and a fresh
process wipes all state.
"""
import uuid
from datetime import timezone

from clock import Clock, format_iso


class DB:
    def __init__(self):
        self.owners = {}
        self.waivers = {}
        self.stalls = {}
        self.horses = {}
        self.agreements = {}
        self.lessons = {}
        self.visits = {}
        self.entries = {}
        self.turnouts = {}
        self.invoices = {}
        self.clock = Clock()
        # monotonic sequence to break created_at ties deterministically for sorting
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_real_iso():
    """Server wall-clock timestamp for envelope meta and created_at/updated_at.

    PRD §2.4: created_at / updated_at are recorded at the moment of creation /
    mutation. These are real server timestamps (record-keeping), distinct from the
    logical business clock used for temporal preconditions (§2.11)."""
    from datetime import datetime
    return format_iso(datetime.now(timezone.utc))
