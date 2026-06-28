"""In-memory data store. Every collection is a dict keyed by id.

PRD 2.4: ids are server-minted UUIDs with no type prefix; created_at, updated_at
are ISO 8601 UTC (three fractional digits) and version begins at its initial value
and increments by one on every mutation. ChainOfCustodyEvent carries only id and
created_at (append-only, immutable).

State is module-level and lives only for the lifetime of the process. start.sh
re-invocation launches a fresh process, which re-imports this module with empty
collections — wiping every byte of prior state. Nothing is seeded here.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.test_panels = {}
        self.lab_partners = {}
        self.phlebotomists = {}
        self.route_days = {}
        self.lab_orders = {}
        self.appointments = {}
        self.draw_kits = {}
        self.specimens = {}
        self.custody_events = {}
        self.courier_manifests = {}
        self.lab_results = {}
        self.invoices = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock ISO 8601 UTC with three fractional digits for created_at/updated_at."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_common(record):
    """Attach id, created_at, updated_at, version to a new common-fields record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Mark a record mutated: bump version, refresh updated_at (PRD 2.5)."""
    record["version"] += 1
    record["updated_at"] = now_iso()
    return record
