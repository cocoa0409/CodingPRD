"""In-memory data store, logical clock and record helpers.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded: every entity is created through the declared API surface.
"""
import uuid
from datetime import datetime, timezone

# PRD 2.5: the logical clock starts at exactly 2026-08-01T00:00:00Z.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.carriers = {}
        self.agreements = {}
        self.offers = {}
        self.trunk_groups = {}
        self.measurements = {}
        self.augment_orders = {}
        self.tariff_filings = {}
        self.factor_filings = {}
        self.usage_batches = {}
        self.cdrs = {}
        self.invoices = {}
        self.disputes = {}
        self.recon_cases = {}
        self.ledger_entries = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def base_record(with_version=True):
    """Common system fields (PRD 2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(row):
    """Mutation bookkeeping: refresh updated_at, bump version by exactly 1."""
    if "version" in row:
        row["updated_at"] = now()
        row["version"] = row["version"] + 1
    return row


def sort_key(row):
    return (row["created_at"], row["_seq"])


def ordered(collection):
    """Every collection is ordered by created_at ascending; insertion order
    breaks ties (PRD 2.3)."""
    rows = collection.values() if isinstance(collection, dict) else collection
    return sorted(rows, key=sort_key)
