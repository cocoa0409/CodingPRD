"""In-memory data store. Starts empty on every boot — no seeding, no preload.

Storage is plain Python dicts keyed by UUID id. A single global simulated clock
supplies "now" for every server-stamped timestamp and every deadline
comparison (PRD §2.5).
"""
import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collection name -> { id: record }
        self.plans = {}
        self.beneficiaries = {}
        self.events = {}
        self.notices = {}
        self.enrollments = {}
        self.accounts = {}
        self.invoices = {}
        self.payments = {}
        self.subsidies = {}
        self.certificates = {}
        # creation ordering counter so list endpoints can tie-break stable sort
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
