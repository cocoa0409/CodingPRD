"""In-memory data store.

The store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded. Every row is created by an API call.
"""
import uuid

from clock import clock


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.publishers = {}
        self.journals = {}
        self.agreements = {}
        self.coverages = {}
        self.authors = {}
        self.funders = {}
        self.grants = {}
        self.articles = {}
        self.determinations = {}
        self.funds = {}
        self.fund_requests = {}
        self.allocations = {}
        self.invoices = {}
        self.deposits = {}
        self._insert_seq = 0
        self.publication_sequence = 0
        self.ingest_sequence = 0

    def next_insert_seq(self):
        self._insert_seq += 1
        return self._insert_seq

    def next_publication_sequence(self):
        self.publication_sequence += 1
        return self.publication_sequence

    def next_ingest_sequence(self):
        self.ingest_sequence += 1
        return self.ingest_sequence


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(**fields):
    """Row carrying the full common field set (PRD 2.4)."""
    now = clock.now_iso()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    row.update(fields)
    return row


def new_ledger_row(**fields):
    """Append-only ledger row: only id and created_at (PRD 2.4)."""
    row = {
        "id": new_id(),
        "created_at": clock.now_iso(),
        "_seq": db.next_insert_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


def set_fields(row, _force=False, **changes):
    """Apply changes; refresh updated_at and bump version when something moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed or _force:
        touch(row)
    return changed


def sort_rows(rows):
    """created_at ascending, insertion order as the stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
