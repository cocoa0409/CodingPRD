"""In-memory data store. No persistence, no seeding — starts empty every boot."""
import itertools
import uuid
from datetime import datetime, timezone


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    """A keyed collection of records for one entity type."""

    def __init__(self):
        self.items = {}  # id -> record dict

    def put(self, record):
        self.items[record["id"]] = record
        return record

    def get(self, rid):
        return self.items.get(rid)

    def all(self):
        # Returned in insertion order (Python dict preserves it); callers that
        # need chronological order sort by _seq for a stable tie-break.
        return list(self.items.values())


class DB:
    def __init__(self):
        # Monotonic sequence used as the canonical chronological tie-break so
        # that records created within the same millisecond still order by
        # actual creation order (ids never decide ordering).
        self._seq = itertools.count(1)
        self.covered_entities = Store()
        self.child_sites = Store()
        self.prescribers = Store()
        self.patients = Store()
        self.drug_products = Store()
        self.ceiling_prices = Store()
        self.contract_pharmacies = Store()
        self.accumulators = Store()
        self.dispenses = Store()
        self.medicaid_claims = Store()
        self.audit_findings = Store()
        self.repayment_obligations = Store()
        self.purchase_orders = Store()

    def next_seq(self):
        return next(self._seq)


# Single module-level instance. Recreated fresh on every process boot.
db = DB()


def base_record(full_meta=True):
    """Create a record with id/created_at (+ updated_at/version when full_meta)."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if full_meta:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version. PRD §2.4."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
