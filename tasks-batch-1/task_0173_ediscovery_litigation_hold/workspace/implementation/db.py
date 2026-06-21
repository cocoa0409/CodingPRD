"""In-memory data store. Every dict is keyed by entity id (UUID4 string).

State starts empty on every boot. No seeding, no preloading, no hardcoded data.
"""
import uuid

import clock

# Entity collections keyed by id.
matters = {}
custodians = {}
legal_holds = {}
hold_acknowledgements = {}
collection_scopes = {}
documents = {}
processing_jobs = {}
review_batches = {}
document_reviews = {}
production_sets = {}
production_items = {}
clawbacks = {}

# Monotonic creation sequence so that resources created within the same pinned
# clock instant retain a stable, deterministic insertion order for sorting and
# chronological dedup/Bates tie-breaks.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def base_fields(common=True):
    """Return the shared system-managed fields for a new resource.

    common=True -> full set (id, created_at, updated_at, version).
    common=False -> ProductionItem set (id, created_at only).
    """
    ts = clock.iso_now()
    seq = next_seq()
    if common:
        return {
            "id": new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": seq,
        }
    return {
        "id": new_id(),
        "created_at": ts,
        "_seq": seq,
    }


def touch(entity):
    """Refresh updated_at and bump version on a full-field resource."""
    entity["updated_at"] = clock.iso_now()
    entity["version"] = entity.get("version", 1) + 1
