"""In-memory data store (PRD §2.4).

Each entity collection is a plain dict keyed by the entity's UUID `id`. The
store starts empty on every process boot — NOTHING is seeded or preloaded.

Common fields (PRD §2.4):
  * id          — server-minted UUID, no type prefix
  * created_at  — fixed at creation, ISO 8601 UTC, 3 fractional digits
  * updated_at  — refreshed on every mutation
  * version     — starts at 1, +1 on every mutation

VisitPhoto and LedgerEntry are append-only/leaner: only `id` + `created_at`
(no updated_at, no version).
"""
import uuid

from clock import next_seq, now_iso_realtime

# One dict per entity collection. Keyed by id.
accounts = {}
properties = {}
quotes = {}
agreements = {}
crews = {}
routes = {}
visits = {}
visit_addons = {}
visit_photos = {}
reclean_requests = {}
invoices = {}
deposits = {}
weather_advisories = {}
ledger_entries = {}

# Map source_type for a payment ledger entry; payments have no own entity, the
# invoice id serves as the source. Re-clean credit uses the reclean request id.


def new_id():
    return str(uuid.uuid4())


def new_record(collection, fields, leaner=False):
    """Create a record with common fields and insert it into `collection`.

    `leaner=True` omits updated_at and version (VisitPhoto, LedgerEntry).
    Returns the stored record dict.
    """
    rid = new_id()
    ts = now_iso_realtime()
    rec = {"id": rid, "created_at": ts}
    rec["_seq"] = next_seq()  # internal creation-order key; stripped on output
    if not leaner:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    collection[rid] = rec
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at and bump version (PRD §2.4)."""
    if "version" in rec:
        rec["version"] = rec.get("version", 1) + 1
        rec["updated_at"] = now_iso_realtime()
    return rec
