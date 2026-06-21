"""In-memory data store. All state lives in module globals so a fresh process
boot (per-test-server isolation) starts completely empty. No seeding.
"""
import uuid

from clock import now_iso, next_seq

# One dict per entity type, keyed by id.
catalogs = {}
garment_units = {}
customers = {}
measurement_profiles = {}
reservations = {}
alterations = {}
party_orders = {}
settlements = {}
fit_checks = {}
ledger_entries = {}

# Internal ordering key map: id -> monotone insertion sequence. created_at is
# the documented tie-break key (PRD §2.4); when two records share the same
# logical-clock created_at string, this sequence preserves deterministic order.
_seq_index = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Apply system-managed creation fields with full quartet."""
    ts = now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    _seq_index[record["id"]] = next_seq()
    return record


def stamp_create_ledger(record):
    """LedgerEntry carries only id + created_at (PRD §2.4)."""
    record.setdefault("id", new_id())
    record["created_at"] = now_iso()
    _seq_index[record["id"]] = next_seq()
    return record


def touch(record):
    """Apply system-managed mutation fields: bump updated_at and version."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def seq_of(record):
    return _seq_index.get(record["id"], 0)
