"""In-memory data store. Module-level singleton; wiped on every process boot."""
import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.sponsors = {}
        self.facilities = {}
        self.programs = {}
        self.projects = {}
        self.applications = {}
        self.assurances = {}
        self.grants = {}
        self.amendments = {}
        self.contractors = {}
        self.contracts = {}
        self.dbe_reports = {}
        self.invoices = {}
        self.reimbursements = {}
        self.findings = {}
        self.assets = {}
        self.phases = {}
        self.grant_seq = {}  # (loc_id, fiscal_year) -> int counter
        # Logical clock: default exactly 2026-05-01T00:00:00Z; never wall-clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-05-01T00:00:00Z"
        # Monotonic timestamp generator state (for created_at/updated_at).
        self._last_ts = self.clock
        self._insert_seq = itertools.count(1)


DB = Store()
