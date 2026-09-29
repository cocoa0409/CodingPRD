"""In-memory data store.

Every collection starts EMPTY on every boot. No seeding, no preloading.
"""

import itertools
import uuid
from datetime import datetime, timezone

# Cold-start default of the logical clock (PRD §2.4).
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "employers",
    "benefit_plans",
    "employees",
    "dependents",
    "providers",
    "credentials",
    "capacity_blocks",
    "reservations",
    "match_offers",
    "ledger_entries",
    "employer_invoices",
    "invoice_lines",
    "incident_reports",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def clock():
    return db.current_utc
