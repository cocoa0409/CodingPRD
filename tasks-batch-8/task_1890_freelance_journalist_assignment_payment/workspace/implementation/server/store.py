"""In-memory data store + logical clock. State lives only in this process;
every start.sh re-invocation boots a fresh, empty store."""

import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.contributors = {}
        self.rate_agreements = {}
        self.assignments = {}
        self.expense_claims = {}
        self.verification_reports = {}
        self.rights_purchases = {}
        self.tax_documents = {}
        self.invoices = {}
        self.payment_batches = {}
        self.ledger_entries = {}
        self.desk_config = None
        self.seq = 0
        self.clock = CLOCK_START


STORE = Store()


def now():
    return STORE.clock


def next_seq():
    STORE.seq += 1
    return STORE.seq


def new_entity():
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(e):
    """Refresh updated_at and bump version (called at most once per entity per request)."""
    e["updated_at"] = now()
    e["version"] += 1
