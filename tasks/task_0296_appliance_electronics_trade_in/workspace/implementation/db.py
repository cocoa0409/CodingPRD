"""In-memory data store.

Storage is process-local Python dicts keyed by id. Nothing is persisted to
disk and NOTHING is seeded at import time — every entity is created through the
declared API surface. A fresh process therefore starts with a completely empty
store, which is what `--isolation per-test-server` relies on.
"""


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.catalogs = {}
        self.device_models = {}
        self.promotion_campaigns = {}
        self.customers = {}
        self.trade_ins = {}
        self.quotes = {}
        self.shipping_kits = {}
        self.inspections = {}
        self.inspection_slots = {}
        self.payouts = {}
        self.data_wipe_certificates = {}
        self.disposition_records = {}
        # Monotonic counter so created_at ties break by insertion order for sorting.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
