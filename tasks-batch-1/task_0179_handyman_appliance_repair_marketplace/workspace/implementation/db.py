"""In-memory data store. Starts EMPTY on every boot — no seeding, no preload.

Storage is plain Python dicts keyed by UUID id. A single global simulated clock
supplies "now" for every server-stamped timestamp and every deadline comparison
(PRD §2.4, §3.8 warranty math, §3.6 visit-window math). The clock can be pinned
by POST /_clock/set_current_utc for deterministic temporal tests.
"""
import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collection name -> { id: record }
        self.service_categories = {}
        self.customers = {}
        self.pros = {}
        self.jobs = {}
        self.quotes = {}
        self.dispatch_windows = {}
        self.labor_lines = {}
        self.part_lines = {}
        self.work_visits = {}
        self.invoices = {}
        self.disputes = {}
        self.background_checks = {}
        # creation ordering counter for stable list sort tie-break
        self._seq = 0
        # global simulated clock; defaults to real wall-clock now until set.
        self._clock = datetime.now(timezone.utc)

    # ---- ids / sequencing -------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- clock ------------------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt
        return self._clock


store = Store()
