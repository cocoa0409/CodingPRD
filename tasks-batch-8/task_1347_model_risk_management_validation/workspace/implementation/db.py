"""In-memory data store. The store starts EMPTY on every boot — no seeding.

All state lives in module-level dictionaries of a single Store instance.
The logical clock defaults to exactly 2026-08-01T00:00:00Z at startup and is
only ever moved by POST /_clock/set_current_utc; nothing here ever consults
wall-clock time.
"""
import itertools
import threading

from utils import parse_iso

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self._seq = itertools.count(1)

        self.models = {}
        self.documentations = {}
        self.change_requests = {}
        self.engagements = {}
        self.findings = {}
        self.metrics = {}
        self.readings = {}
        self.breach_events = {}
        self.assessments = {}
        self.reports = {}

        # Logical clock. clock_raw preserves the exact string the PlatformAdmin
        # supplied so the clock endpoint can echo it back verbatim.
        self.clock_raw = DEFAULT_CLOCK_ISO
        self.clock_dt = parse_iso(DEFAULT_CLOCK_ISO)

    def next_seq(self):
        """Monotonic insertion sequence used as a deterministic sort tiebreak."""
        return next(self._seq)

    def now(self):
        """Logical-clock now — never wall-clock."""
        return self.clock_dt


store = Store()
