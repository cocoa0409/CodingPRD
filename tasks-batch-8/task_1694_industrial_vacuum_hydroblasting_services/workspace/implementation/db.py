"""In-memory data store. Fresh per process; nothing is seeded at startup."""

from datetime import datetime, timezone


def _default_clock():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.sites = {}
        self.rate_schedules = {}
        self.jobs = {}
        self.jhas = {}
        self.permits = {}
        self.equipment_units = {}
        self.operators = {}
        self.assignments = {}
        self.waste_profiles = {}
        self.facilities = {}
        self.manifests = {}
        self.containment_records = {}
        self.downtime_events = {}
        self.invoices = {}
        self.incidents = {}
        # Logical clock: reads exactly 2026-08-01T00:00:00Z before being set;
        # never falls back to wall-clock time.
        self.clock = _default_clock()
        # Global job creation sequence (1-based), used in invoice numbering.
        self.job_seq = 0


store = Store()
