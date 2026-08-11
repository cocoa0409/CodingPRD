"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone


def _default_clock():
    return datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clients = {}
        self.service_agreements = {}
        self.batches = {}
        self.boxes = {}
        self.documents = {}
        self.scan_sessions = {}
        self.page_logs = {}
        self.index_records = {}
        self.access_grants = {}
        self.custody_events = {}
        self.destruction_certificates = {}
        self.scanner_units = {}
        self.shelf_slots = {}
        self.shelf_assignments = {}
        self.invoices = {}
        # Logical clock
        self.current_utc = _default_clock()
        # Monotonic insertion counter: the logical clock does not advance
        # between requests, so created_at ties are routine. Domain ordering
        # that must reflect real insertion order (e.g. the "greatest
        # created_at" custody link) uses this tiebreak.
        self.seq = 0

    def reset(self):
        self.__init__()


db = Store()
