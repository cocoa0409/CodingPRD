"""In-memory data store.

Per-test-server isolation wipes all state on every restart, so the store MUST
start empty on every boot. NEVER seed any entity here.
"""
import itertools
import uuid

from clock import iso_millis


class Store:
    def __init__(self, clock):
        self.clock = clock
        # one dict per entity collection, keyed by id
        self.students = {}
        self.corporate_contracts = {}
        self.placement_tests = {}
        self.cohorts = {}
        self.enrollments = {}
        self.attendance_records = {}
        self.progress_reports = {}
        self.add_ons = {}
        self.compliance_events = {}
        # monotonic creation sequence — used as a stable tie-break for "created_at
        # ascending" ordering, since multiple records can share the same wall-clock
        # millisecond timestamp.
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


def now_iso(store):
    """Wall-clock creation/modification timestamp (audit fields, PRD §2.4)."""
    import datetime

    return iso_millis(datetime.datetime.now(datetime.timezone.utc))
