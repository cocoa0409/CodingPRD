"""In-memory data store.

Storage is in-memory only. The store starts empty on every boot — no seeding,
no preloaded entities. Each fresh process begins with a clean slate.

Common system fields (PRD §2.4):
  - id          : UUID, no type prefix
  - created_at  : ISO 8601 UTC, 3 fractional digits, set at creation
  - updated_at  : ISO 8601 UTC, 3 fractional digits, refreshed on every mutation
  - version     : integer starting at 1, +1 on every mutation

ConsentWaiver is the exception: only id + created_at (+ signed_at == created_at);
no updated_at, no version.
"""
import uuid

from clock import now_iso_millis

# One dict per entity type, keyed by id.
artists = {}
clients = {}
flash_designs = {}
custom_requests = {}
appointments = {}
chairs = {}
deposits = {}
waivers = {}
touchups = {}
portfolio_items = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record, *, versioned=True):
    """Populate id/created_at/updated_at/version for a new record."""
    ts = now_iso_millis()
    record["id"] = new_id()
    record["created_at"] = ts
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = now_iso_millis()
    record["version"] = record.get("version", 1) + 1
    return record
