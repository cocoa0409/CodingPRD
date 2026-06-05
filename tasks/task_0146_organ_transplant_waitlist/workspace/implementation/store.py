"""In-memory data store. Empty on every boot — NO seeding, NO preload.

Each entity collection is a dict keyed by the entity's UUID id. The system
clock (PRD §2.5) is a server-owned singleton. A monotonically increasing
sequence stamps an insertion order so list endpoints can sort by creation
time deterministically even when two rows share a created_at instant.
"""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.transplant_centers = {}
        self.opos = {}
        self.candidates = {}
        self.clinical_scores = {}
        self.registrations = {}
        self.donor_organs = {}
        self.match_runs = {}
        self.match_list_entries = {}
        self.offers = {}
        self.transplants = {}
        self.follow_ups = {}
        self.unos_reports = {}
        # Deterministic clock singleton (PRD §2.5). Defaults to a fixed epoch
        # so reads before any /_clock/set_current_utc are still well-defined.
        self.clock = datetime(1970, 1, 1, tzinfo=timezone.utc)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
