"""In-memory data store.

The store starts EMPTY on every boot — nothing is seeded. Every entity any test
needs is constructed by the test itself through the declared API surface.

One dict per entity collection, keyed by id. Insertion order is preserved by
Python dicts, which we rely on for created_at-ascending list ordering.
"""

import threading


class DB:
    def __init__(self):
        self.license_boards = {}
        self.credit_requirements = {}
        self.providers = {}
        self.courses = {}
        self.licensees = {}
        self.renewal_cycles = {}
        self.completions = {}
        self.certificates = {}
        self.audits = {}
        self.attestations = {}
        self.reciprocity_grants = {}

        # Per-board monotonic certificate serial counters, keyed by board_id.
        self.cert_serial_counters = {}

        # A single coarse lock guards all mutations; correctness over throughput.
        self.lock = threading.RLock()


db = DB()
