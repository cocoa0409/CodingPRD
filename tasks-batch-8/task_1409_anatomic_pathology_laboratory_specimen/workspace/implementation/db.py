"""In-memory data store plus the laboratory logical clock.

The store starts EMPTY on every boot (per-test-server isolation re-launches
the process before every test). No seeding anywhere.
"""
import threading
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.patients = {}
        self.pathologists = {}
        self.coverage_windows = {}
        self.cases = {}
        self.specimens = {}
        self.blocks = {}
        self.slides = {}
        self.stain_orders = {}
        self.reflex_rules = {}
        self.reports = {}
        self.consultations = {}
        self.discrepancies = {}
        self.release_requests = {}
        # accession-number sequence per calendar year
        self.accession_seq = {}
        # monotonic insertion counter for deterministic ordering
        self.seq = 0
        # The laboratory logical clock. Startup default is exactly
        # 2026-08-01T00:00:00Z; it never falls back to wall time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()
