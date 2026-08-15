"""In-memory data store and the program's logical clock.

The store starts EMPTY on every boot — no seeding. Every entity a test needs
is constructed through the declared API surface.

The logical clock (PRD §2.4) governs every server-stamped timestamp and every
temporal rule. Before it has ever been set it reads exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import threading
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # entity tables, keyed by id
        self.caretakers = {}
        self.colonies = {}
        self.cats = {}
        self.partner_clinics = {}
        self.clinic_days = {}
        self.clinic_slots = {}
        self.appointments = {}
        self.surgery_records = {}
        self.vouchers = {}
        self.complaints = {}
        self.foster_homes = {}
        self.foster_placements = {}
        self.population_surveys = {}
        # logical clock (datetime, tz-aware UTC)
        self.clock = DEFAULT_CLOCK
        # monotone insertion sequence for stable created_at tie-breaking
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


# The single process-wide store. A fresh process (per-test server restart)
# gets a fresh, empty store.
db = Store()

# Serializes request handling so concurrent test requests cannot interleave
# mutations.
LOCK = threading.RLock()
