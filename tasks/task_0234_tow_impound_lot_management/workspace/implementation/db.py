"""In-memory data store. Every collection is a plain dict keyed by id.
NOTHING is seeded — the store is empty on every process boot. Tests build all
preconditions through the declared API surface."""
import uuid

from clock import iso, now

# Each collection: id -> record dict.
impound_lots = {}
tow_providers = {}
lienholders = {}
rotation_assignments = {}
tow_orders = {}
notifications = {}
inventory_items = {}
fee_waivers = {}
release_records = {}
auctions = {}
ledger_entries = {}

# Monotonic insertion sequence used as a deterministic tiebreaker for ordering
# (created_at ASC; if two share a created_at the lower _seq wins).
_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Apply common system fields on create (id, created_at, updated_at, version, _seq)."""
    ts = now()
    record["id"] = new_id()
    record["created_at"] = iso(ts)
    record["updated_at"] = iso(ts)
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump updated_at + version on mutation (PRD §2.4 / §2.9)."""
    record["updated_at"] = iso(now())
    record["version"] = record.get("version", 1) + 1
    return record
