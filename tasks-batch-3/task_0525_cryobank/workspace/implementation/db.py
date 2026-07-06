import uuid

from clock import Clock, iso_millis


class Store:
    """In-memory data store. Fresh (empty) on every process boot."""

    def __init__(self):
        self.clock = Clock()
        # entity collections keyed by id
        self.donors = {}
        self.screening_applications = {}
        self.specimens = {}
        self.donor_inventories = {}
        self.recipients = {}
        self.recipient_consents = {}
        self.vial_reservations = {}
        self.shipments = {}
        self.storage_accounts = {}
        self.storage_invoices = {}
        self.sibling_registry = {}
        self.collection_appointments = {}
        self.dewar_maintenance_windows = {}
        self.regulatory_reports = {}
        # monotonic creation counter for stable ascending sort
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock.now()


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_fields(store):
    """Common system fields: id, created_at, updated_at, version, plus a hidden seq."""
    now = store.now()
    ts = iso_millis(now)
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
        "_created_dt": now,
    }


def touch(store, entity):
    """Mark an entity mutated: bump version + updated_at."""
    entity["version"] += 1
    entity["updated_at"] = iso_millis(store.now())
