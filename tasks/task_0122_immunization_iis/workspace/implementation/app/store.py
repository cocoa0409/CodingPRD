"""In-memory data store. UUID minting, common-field stamping, and lookups.

The store is intentionally simple: dict-of-dict keyed by entity id. A single
RLock serializes all writes — this makes the concurrency rules in the PRD
"first-writer-wins" trivially correct, since Python's GIL plus an outer lock
yields the desired serial semantics for in-process tests.
"""
from __future__ import annotations

import uuid
from threading import RLock
from typing import Any, Dict, Optional

from .clock import format_iso, now


# Each entity collection is a {id: record_dict}. Mutating helpers below stamp
# common fields (created_at, updated_at, version) per the PRD.
patients: Dict[str, dict] = {}
vaccine_products: Dict[str, dict] = {}
vaccine_lots: Dict[str, dict] = {}
provider_organizations: Dict[str, dict] = {}
administered_doses: Dict[str, dict] = {}
allergy_records: Dict[str, dict] = {}
adverse_events: Dict[str, dict] = {}
antigen_schedule_rules: Dict[str, dict] = {}
school_certificates: Dict[str, dict] = {}


# Single RLock for all mutations. Read paths don't need it because the GIL
# atomizes dict reads, and the data model is small.
lock = RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def reset_all() -> None:
    """Wipe every in-memory collection. Used by the test reset endpoint."""
    with lock:
        patients.clear()
        vaccine_products.clear()
        vaccine_lots.clear()
        provider_organizations.clear()
        administered_doses.clear()
        allergy_records.clear()
        adverse_events.clear()
        antigen_schedule_rules.clear()
        school_certificates.clear()


def stamp_create(record: dict, *, include_version: bool = True) -> dict:
    """Add system-managed fields onto a freshly-created entity."""
    ts = format_iso(now())
    record.setdefault("id", new_id())
    record["created_at"] = ts
    if include_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def stamp_update(record: dict) -> dict:
    """Refresh updated_at and bump version by exactly 1."""
    if "version" not in record:
        # Defensive; should never happen for entities with common_fields=true.
        record["version"] = 1
        record["updated_at"] = format_iso(now())
        return record
    record["version"] = record["version"] + 1
    record["updated_at"] = format_iso(now())
    return record
