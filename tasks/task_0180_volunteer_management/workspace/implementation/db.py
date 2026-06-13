"""In-memory data store. Starts EMPTY on every boot — no seeding, no preload.

Storage is plain Python dicts keyed by UUID id (PRD §2.4: id is a bare UUID with
no type prefix). A single global simulated clock supplies "now" for every
server-stamped timestamp and every time-gated comparison (PRD §2.8). The clock
can be pinned via POST /_clock/set_current_utc for deterministic temporal tests.
"""
import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collection name -> { id: record }
        self.organizations = {}
        self.volunteers = {}
        self.background_checks = {}
        self.skills = {}
        self.volunteer_skills = {}
        self.waiver_templates = {}
        self.waiver_acceptances = {}
        self.training_modules = {}
        self.training_completions = {}
        self.opportunities = {}
        self.shifts = {}
        self.signups = {}
        self.corporate_groups = {}
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
