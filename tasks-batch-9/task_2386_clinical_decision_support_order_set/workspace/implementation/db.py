"""In-memory data store.

The store is EMPTY at boot.  Nothing is seeded, preloaded or hardcoded — every
record is created through the declared API surface.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # entity tables — all keyed by the server-minted uuid
        self.clinicians = {}
        self.content_requests = {}
        self.order_sets = {}
        self.order_set_items = {}
        self.alerts = {}
        self.burden_windows = {}
        self.override_events = {}
        self.review_assignments = {}
        self.vendor_releases = {}
        self.vendor_deltas = {}
        self.downtime_events = {}
        self.adherence_measurements = {}
        self.annual_review_tasks = {}
        # logical clock (PRD §2.4) — starts at the documented epoch
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # monotonic insertion counter used only for deterministic tie-breaking
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def snapshot(self):
        import copy
        return copy.deepcopy(self.__dict__)

    def restore(self, snap):
        self.__dict__.clear()
        self.__dict__.update(snap)


db = Store()
